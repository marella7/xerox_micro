# Student Cut Mode

A Flask app that arranges a PDF into paired A4 landscape sheets for double-sided
printing. Each front and back side contains up to 8 pages in a 4-column by
2-row grid. Pages are placed without rotation.

## Run locally

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5000> in your browser. Upload a PDF up to 100 MB, preview
the first front/back pair, and download the generated PDF. Temporary job files
older than one hour are removed when another PDF is processed.

## Page order

Each 16-page batch is placed in row-major order:

```text
Front:  1  3  5  7       Back:  8  6  4  2
        9 11 13 15              16 14 12 10
```

The final partial batch is also emitted as a front/back pair; unused cells are
left blank.

## Run tests

```powershell
python -m unittest discover -s tests
```

## Deploy to Render

The included `render.yaml` configures a Python web service named
`student-cut-mode`. Push this project to a GitHub repository, then in Render
choose **New > Blueprint** and connect that repository. Render reads
`render.yaml`, installs `requirements.txt`, and starts the app with Gunicorn.

The Gunicorn dependency is excluded on Windows because it requires a Unix-like
server environment; Render installs it on its Linux runtime.

After deployment, Render provides a public `onrender.com` address. To make the
site discoverable by searching its name, add and verify the deployed URL in
Google Search Console and request indexing. Search indexing and ranking are
controlled by Google and are not immediate or guaranteed.

The current app stores generated files in temporary local storage and deletes
expired jobs when another PDF is processed. This is suitable for trying out the
service, but files may be lost when a hosted service restarts.
