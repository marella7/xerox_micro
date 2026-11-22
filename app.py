from __future__ import annotations

import logging
import shutil
import time
import uuid
from io import BytesIO
from pathlib import Path

import pymupdf as fitz
from flask import Flask, abort, jsonify, render_template, request, send_file
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from werkzeug.exceptions import RequestEntityTooLarge

MAX_UPLOAD_BYTES = 100 * 1024 * 1024
JOB_TTL_SECONDS = 60 * 60
SHEET_WIDTH = 842
SHEET_HEIGHT = 595
GRID_COLUMNS = 4
GRID_ROWS = 2

FRONT_PAGE_OFFSETS = (0, 2, 4, 6, 8, 10, 12, 14)
BACK_PAGE_OFFSETS = (7, 5, 3, 1, 15, 13, 11, 9)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES + 1024 * 1024
app.config["JOBS_DIR"] = Path(app.instance_path) / "student_cut_jobs"
app.config["JOBS_DIR"].mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO)


class PdfInputError(ValueError):
    """Raised when an uploaded file cannot be processed as a supported PDF."""


def _is_scanned_page(page: fitz.Page) -> bool:
    return len(page.get_text("text").strip()) < 20 and bool(page.get_images(full=True))


def _enhance_scanned_page(page: fitz.Page) -> bytes:
    """Render, crop, contrast-enhance, denoise, and sharpen one scanned page."""
    pixmap = page.get_pixmap(
        matrix=fitz.Matrix(300 / 72, 300 / 72),
        alpha=False,
        colorspace=fitz.csRGB,
    )
    image = Image.frombytes(
        "RGB",
        (pixmap.width, pixmap.height),
        pixmap.samples,
    )

    grayscale = ImageOps.grayscale(image)
    content_mask = grayscale.point(
        lambda value: 0 if value > 248 else 255
    )
    content_box = content_mask.getbbox()
    if content_box:
        padding = 14
        left = max(0, content_box[0] - padding)
        top = max(0, content_box[1] - padding)
        right = min(image.width, content_box[2] + padding)
        bottom = min(image.height, content_box[3] + padding)
        image = image.crop((left, top, right, bottom))

    image = ImageOps.autocontrast(image, cutoff=1)
    image = ImageEnhance.Contrast(image).enhance(1.12)
    image = image.filter(ImageFilter.MedianFilter(size=3))
    image = image.filter(
        ImageFilter.UnsharpMask(radius=1.2, percent=155, threshold=3)
    )

    encoded = BytesIO()
    image.save(encoded, format="JPEG", quality=94, subsampling=0, optimize=True)
    return encoded.getvalue()


def create_student_cut_pdf(
    input_data: bytes,
    output_path: Path,
    enhance_scanned: bool = False,
) -> int:
    """Create A4 landscape front/back sheets using the Student Cut Mode order."""
    if not input_data:
        raise PdfInputError("The uploaded file is empty.")

    try:
        input_pdf = fitz.open(stream=input_data, filetype="pdf")
    except (fitz.FileDataError, fitz.EmptyFileError) as exc:
        raise PdfInputError("The uploaded file is not a valid PDF.") from exc

    with input_pdf:
        if input_pdf.needs_pass:
            raise PdfInputError("Password-protected PDFs are not supported.")

        total_pages = len(input_pdf)
        if total_pages == 0:
            raise PdfInputError("The PDF does not contain any pages.")

        cell_width = SHEET_WIDTH / GRID_COLUMNS
        cell_height = SHEET_HEIGHT / GRID_ROWS

        with fitz.open() as output_pdf:
            for batch_start in range(0, total_pages, 16):
                front = output_pdf.new_page(
                    width=SHEET_WIDTH,
                    height=SHEET_HEIGHT,
                )
                for position, offset in enumerate(FRONT_PAGE_OFFSETS):
                    page_number = batch_start + offset
                    if page_number >= total_pages:
                        continue

                    column = position % GRID_COLUMNS
                    row = position // GRID_COLUMNS
                    rect = fitz.Rect(
                        column * cell_width,
                        row * cell_height,
                        (column + 1) * cell_width,
                        (row + 1) * cell_height,
                    )
                    if enhance_scanned and _is_scanned_page(input_pdf[page_number]):
                        enhanced_image = _enhance_scanned_page(input_pdf[page_number])
                        front.insert_image(rect, stream=enhanced_image, keep_proportion=True)
                    else:
                        front.show_pdf_page(rect, input_pdf, page_number)

                back = output_pdf.new_page(
                    width=SHEET_WIDTH,
                    height=SHEET_HEIGHT,
                )
                for position, offset in enumerate(BACK_PAGE_OFFSETS):
                    page_number = batch_start + offset
                    if page_number >= total_pages:
                        continue

                    column = position % GRID_COLUMNS
                    row = position // GRID_COLUMNS
                    rect = fitz.Rect(
                        column * cell_width,
                        row * cell_height,
                        (column + 1) * cell_width,
                        (row + 1) * cell_height,
                    )
                    if enhance_scanned and _is_scanned_page(input_pdf[page_number]):
                        enhanced_image = _enhance_scanned_page(input_pdf[page_number])
                        back.insert_image(rect, stream=enhanced_image, keep_proportion=True)
                    else:
                        back.show_pdf_page(rect, input_pdf, page_number)

            output_pdf.save(output_path, garbage=4, deflate=True)

    return total_pages


def _cleanup_expired_jobs() -> None:
    jobs_dir: Path = app.config["JOBS_DIR"]
    expiry_time = time.time() - JOB_TTL_SECONDS
    for job_dir in jobs_dir.iterdir():
        if not job_dir.is_dir():
            continue
        try:
            if job_dir.stat().st_mtime < expiry_time:
                shutil.rmtree(job_dir)
        except OSError:
            app.logger.warning("Could not remove expired job directory %s", job_dir)


def _job_directory(job_id: str) -> Path:
    try:
        normalized_id = uuid.UUID(job_id).hex
    except ValueError:
        abort(404)
    if normalized_id != job_id:
        abort(404)
    return app.config["JOBS_DIR"] / normalized_id


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/process")
def process_pdf():
    uploaded_file = request.files.get("file")
    if uploaded_file is None or not uploaded_file.filename:
        return jsonify(error="Choose a PDF file to continue."), 400

    enhance_scanned = request.form.get("enhance_scanned") == "1"
    input_data = uploaded_file.stream.read(MAX_UPLOAD_BYTES + 1)
    if len(input_data) > MAX_UPLOAD_BYTES:
        return jsonify(error="The PDF must be 100 MB or smaller."), 413

    _cleanup_expired_jobs()
    job_id = uuid.uuid4().hex
    job_dir = app.config["JOBS_DIR"] / job_id
    job_dir.mkdir()
    output_path = job_dir / "Student_Cut_Mode_A4R.pdf"

    try:
        total_pages = create_student_cut_pdf(
            input_data,
            output_path,
            enhance_scanned=enhance_scanned,
        )
    except PdfInputError as exc:
        shutil.rmtree(job_dir)
        return jsonify(error=str(exc)), 400

    with fitz.open(output_path) as result_pdf:
        for page_index in range(min(2, len(result_pdf))):
            page = result_pdf[page_index]
            # Render previews at 300 DPI-equivalent resolution for a clear
            # on-screen image; this does not rasterize or resize the PDF output.
            scale = min(300 / 72, 2400 / page.rect.width)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            pixmap.save(job_dir / f"preview-{page_index + 1}.png")

    return jsonify(
        total_input_pages=total_pages,
        total_output_pages=((total_pages + 15) // 16) * 2,
        enhancement_enabled=enhance_scanned,
        preview_front_url=f"/jobs/{job_id}/preview/1",
        preview_back_url=f"/jobs/{job_id}/preview/2",
        download_url=f"/jobs/{job_id}/download",
    )


@app.get("/jobs/<job_id>/preview/<int:side>")
def preview(job_id: str, side: int):
    if side not in (1, 2):
        abort(404)
    preview_path = _job_directory(job_id) / f"preview-{side}.png"
    if not preview_path.is_file():
        abort(404)
    return send_file(preview_path, mimetype="image/png", max_age=0)


@app.get("/jobs/<job_id>/download")
def download(job_id: str):
    output_path = _job_directory(job_id) / "Student_Cut_Mode_A4R.pdf"
    if not output_path.is_file():
        abort(404)
    return send_file(
        output_path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="Student_Cut_Mode_A4R.pdf",
        max_age=0,
    )


@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(_error):
    return jsonify(error="The PDF must be 100 MB or smaller."), 413


if __name__ == "__main__":
    app.run(debug=False)
