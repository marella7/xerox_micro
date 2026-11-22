from io import BytesIO
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz

from app import PdfInputError, app, create_student_cut_pdf, merge_pdf_inputs


class StudentCutModeTests(unittest.TestCase):
    def make_source_pdf(self, page_count: int) -> bytes:
        with fitz.open() as source:
            for page_number in range(1, page_count + 1):
                page = source.new_page(width=300, height=200)
                page.insert_text((40, 100), f"SOURCE_PAGE_{page_number}")
            return source.tobytes()

    def extract_page_labels_in_grid_order(
        self,
        page: fitz.Page,
    ) -> tuple[list[str], list[tuple[float, float]]]:
        positioned_labels = []
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    if not span["text"].startswith("SOURCE_PAGE_"):
                        continue
                    x0, y0, x1, y1 = span["bbox"]
                    positioned_labels.append(
                        (
                            (y0 + y1) / 2,
                            (x0 + x1) / 2,
                            span["text"],
                            line["dir"],
                        )
                    )

        positioned_labels.sort(key=lambda item: (item[0], item[1]))
        return (
            [item[2] for item in positioned_labels],
            [item[3] for item in positioned_labels],
        )

    def test_exact_front_and_back_order_in_one_batch(self):
        source_data = self.make_source_pdf(16)
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "result.pdf"
            pages_processed = create_student_cut_pdf(source_data, output_path)

            self.assertEqual(pages_processed, 16)
            with fitz.open(output_path) as result:
                self.assertEqual(len(result), 2)
                front_order, front_directions = self.extract_page_labels_in_grid_order(
                    result[0]
                )
                self.assertEqual(
                    front_order,
                    [
                        "SOURCE_PAGE_1",
                        "SOURCE_PAGE_3",
                        "SOURCE_PAGE_5",
                        "SOURCE_PAGE_7",
                        "SOURCE_PAGE_9",
                        "SOURCE_PAGE_11",
                        "SOURCE_PAGE_13",
                        "SOURCE_PAGE_15",
                    ],
                )
                self.assertEqual(set(front_directions), {(1.0, 0.0)})

                back_order, back_directions = self.extract_page_labels_in_grid_order(
                    result[1]
                )
                self.assertEqual(
                    back_order,
                    [
                        "SOURCE_PAGE_8",
                        "SOURCE_PAGE_6",
                        "SOURCE_PAGE_4",
                        "SOURCE_PAGE_2",
                        "SOURCE_PAGE_16",
                        "SOURCE_PAGE_14",
                        "SOURCE_PAGE_12",
                        "SOURCE_PAGE_10",
                    ],
                )
                self.assertEqual(set(back_directions), {(1.0, 0.0)})

    def test_partial_batch_keeps_a_front_and_back_pair(self):
        source_data = self.make_source_pdf(17)
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "result.pdf"
            create_student_cut_pdf(source_data, output_path)

            with fitz.open(output_path) as result:
                self.assertEqual(len(result), 4)
                self.assertEqual(
                    self.extract_page_labels_in_grid_order(result[2])[0],
                    ["SOURCE_PAGE_17"],
                )
                self.assertEqual(
                    self.extract_page_labels_in_grid_order(result[3])[0],
                    [],
                )

    def test_rejects_non_pdf_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "result.pdf"
            with self.assertRaises(PdfInputError):
                create_student_cut_pdf(b"not a PDF", output_path)

    def test_merge_pdf_inputs_keeps_first_then_second_page_order(self):
        first_data = self.make_source_pdf(3)
        second_data = self.make_source_pdf(3)
        merged_data = merge_pdf_inputs([first_data, second_data])

        with fitz.open(stream=merged_data, filetype="pdf") as merged:
            self.assertEqual(len(merged), 6)
            labels = [merged[index].get_text().strip() for index in range(6)]
            self.assertEqual(
                labels,
                [
                    "SOURCE_PAGE_1",
                    "SOURCE_PAGE_2",
                    "SOURCE_PAGE_3",
                    "SOURCE_PAGE_1",
                    "SOURCE_PAGE_2",
                    "SOURCE_PAGE_3",
                ],
            )

    def test_upload_returns_preview_and_downloadable_pdf(self):
        source_data = self.make_source_pdf(2)
        with tempfile.TemporaryDirectory() as temp_dir:
            jobs_dir = Path(temp_dir)
            with patch.dict(app.config, {"JOBS_DIR": jobs_dir}):
                client = app.test_client()
                self.assertEqual(client.get("/").status_code, 200)
                index_response = client.get("/")
                self.assertIn(b"MARELLA product", index_response.data)
                self.assertIn(b"Merge PDFs", index_response.data)
                self.assertIn("Cut 8×8".encode(), index_response.data)
                static_response = client.get("/static/app.js")
                self.assertEqual(static_response.status_code, 200)
                static_response.close()
                response = client.post(
                    "/process",
                    data={"file": (BytesIO(source_data), "study.pdf")},
                    content_type="multipart/form-data",
                )

                self.assertEqual(response.status_code, 200)
                response_data = response.get_json()
                self.assertEqual(response_data["total_input_pages"], 2)
                self.assertEqual(response_data["total_output_pages"], 2)
                front_preview = client.get(response_data["preview_front_url"])
                self.assertEqual(front_preview.mimetype, "image/png")
                front_preview.close()
                back_preview = client.get(response_data["preview_back_url"])
                self.assertEqual(back_preview.mimetype, "image/png")
                back_preview.close()
                download_response = client.get(response_data["download_url"])
                self.assertEqual(download_response.mimetype, "application/pdf")
                with fitz.open(stream=download_response.data, filetype="pdf") as output:
                    self.assertEqual(len(output), 2)
                download_response.close()

    def test_upload_can_merge_two_pdfs(self):
        first_data = self.make_source_pdf(2)
        second_data = self.make_source_pdf(3)
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(app.config, {"JOBS_DIR": Path(temp_dir)}):
                response = app.test_client().post(
                    "/process",
                    data={
                        "merge_pdfs": "1",
                        "file": (BytesIO(first_data), "units-1-3.pdf"),
                        "second_file": (BytesIO(second_data), "units-4-6.pdf"),
                    },
                    content_type="multipart/form-data",
                )

                self.assertEqual(response.status_code, 200)
                response_data = response.get_json()
                self.assertEqual(response_data["total_input_pages"], 5)
                download_response = app.test_client().get(response_data["download_url"])
                with fitz.open(stream=download_response.data, filetype="pdf") as output:
                    self.assertEqual(len(output), 2)
                download_response.close()

    def test_enhanced_scanned_output_contains_processed_jpeg_images(self):
        with fitz.open() as source:
            first = source.new_page(width=300, height=200)
            first.insert_text((40, 100), "SCANNED_PAGE_1")
            rendered = first.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)

            scanned = fitz.open()
            scanned_page = scanned.new_page(width=300, height=200)
            scanned_page.insert_image(
                scanned_page.rect,
                stream=rendered.tobytes("png"),
            )
            source_data = scanned.tobytes()
            scanned.close()

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "enhanced.pdf"
            create_student_cut_pdf(
                source_data,
                output_path,
                enhance_scanned=True,
            )

            with fitz.open(output_path) as result:
                self.assertEqual(len(result), 2)
                enhanced_images = sum(
                    len(result_page.get_images(full=True))
                    for result_page in result
                )
                self.assertGreater(enhanced_images, 0)


if __name__ == "__main__":
    unittest.main()
