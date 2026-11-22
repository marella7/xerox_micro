const form = document.querySelector("#upload-form");
const fileInput = document.querySelector("#pdf-file");
const mergeCheckbox = document.querySelector("#merge-pdfs");
const secondFileContainer = document.querySelector("#second-file");
const secondFileInput = document.querySelector("#second-pdf-file");
const secondFileLabel = document.querySelector("#second-file-label");
const dropZone = document.querySelector("#drop-zone");
const selectedFile = document.querySelector("#selected-file");
const fileName = document.querySelector("#file-name");
const fileSize = document.querySelector("#file-size");
const removeFileButton = document.querySelector("#remove-file");
const submitButton = document.querySelector("#submit-button");
const progressArea = document.querySelector("#progress-area");
const progressBar = document.querySelector("#upload-progress");
const progressMessage = document.querySelector("#progress-message");
const progressValue = document.querySelector("#progress-value");
const statusMessage = document.querySelector("#status-message");
const resultPanel = document.querySelector("#result-panel");
const resultSummary = document.querySelector("#result-summary");
const frontPreview = document.querySelector("#front-preview");
const backPreview = document.querySelector("#back-preview");
const downloadLink = document.querySelector("#download-link");
const modeOptions = document.querySelector("#mode-options");
const mergeModeButton = document.querySelector("#merge-mode");
const cutModeButton = document.querySelector("#cut-mode");
const workspace = document.querySelector("#workspace");
const backButton = document.querySelector("#back-button");
const hero = document.querySelector(".hero");
const mergeOption = mergeCheckbox?.closest(".enhancement-option");

const maxFileSize = 100 * 1024 * 1024;
const bytesInMegabyte = 1024 * 1024;

function openMode(mode) {
  modeOptions.hidden = true;
  workspace.hidden = false;
  hero.hidden = true;

  if (mode === "merge") {
    mergeCheckbox.checked = true;
    if (mergeOption) mergeOption.hidden = true;
    secondFileContainer.hidden = false;
  } else {
    mergeCheckbox.checked = false;
    if (mergeOption) mergeOption.hidden = true;
    secondFileContainer.hidden = true;
  }
}

mergeModeButton.addEventListener("click", () => openMode("merge"));
cutModeButton.addEventListener("click", () => openMode("cut"));

backButton.addEventListener("click", () => {
  modeOptions.hidden = false;
  workspace.hidden = true;
  hero.hidden = false;
  mergeCheckbox.checked = false;
  if (mergeOption) mergeOption.hidden = false;
  secondFileContainer.hidden = true;
  secondFileInput.value = "";
  secondFileLabel.textContent = "Choose the second PDF";
  statusMessage.textContent = "";
  resultPanel.hidden = true;
});

function formatFileSize(bytes) {
  return `${(bytes / bytesInMegabyte).toFixed(1)} MB`;
}

function selectFile(file) {
  statusMessage.textContent = "";
  resultPanel.hidden = true;

  if (!file) {
    fileInput.value = "";
    selectedFile.hidden = true;
    return;
  }

  if (!file.name.toLowerCase().endsWith(".pdf")) {
    fileInput.value = "";
    selectedFile.hidden = true;
    statusMessage.textContent = "Choose a PDF file.";
    return;
  }

  if (file.size > maxFileSize) {
    fileInput.value = "";
    selectedFile.hidden = true;
    statusMessage.textContent = "The PDF must be 100 MB or smaller.";
    return;
  }

  fileName.textContent = file.name;
  fileSize.textContent = formatFileSize(file.size);
  selectedFile.hidden = false;
}

fileInput.addEventListener("change", () => selectFile(fileInput.files[0]));

mergeCheckbox.addEventListener("change", () => {
  secondFileContainer.hidden = !mergeCheckbox.checked;
  if (!mergeCheckbox.checked) {
    secondFileInput.value = "";
    secondFileLabel.textContent = "Choose the second PDF";
  }
});

secondFileInput.addEventListener("change", () => {
  const file = secondFileInput.files[0];
  statusMessage.textContent = "";
  if (!file) {
    secondFileLabel.textContent = "Choose the second PDF";
    return;
  }
  if (!file.name.toLowerCase().endsWith(".pdf")) {
    secondFileInput.value = "";
    secondFileLabel.textContent = "Choose the second PDF";
    statusMessage.textContent = "Choose a PDF file.";
    return;
  }
  if (file.size > maxFileSize) {
    secondFileInput.value = "";
    secondFileLabel.textContent = "Choose the second PDF";
    statusMessage.textContent = "Each PDF must be 100 MB or smaller.";
    return;
  }
  secondFileLabel.textContent = file.name;
});

removeFileButton.addEventListener("click", () => {
  selectFile(null);
  fileInput.focus();
});

for (const eventName of ["dragenter", "dragover"]) {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.add("is-dragging");
  });
}

for (const eventName of ["dragleave", "drop"]) {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.remove("is-dragging");
  });
}

dropZone.addEventListener("drop", (event) => {
  const [file] = event.dataTransfer.files;
  if (!file) {
    return;
  }

  const transfer = new DataTransfer();
  transfer.items.add(file);
  fileInput.files = transfer.files;
  selectFile(file);
});

form.addEventListener("submit", (event) => {
  event.preventDefault();
  statusMessage.textContent = "";
  resultPanel.hidden = true;

  const file = fileInput.files[0];
  if (!file) {
    statusMessage.textContent = "Choose a PDF file to continue.";
    return;
  }
  if (mergeCheckbox.checked && !secondFileInput.files[0]) {
    statusMessage.textContent = "Choose the second PDF to merge.";
    return;
  }

  const request = new XMLHttpRequest();
  request.open("POST", "/process");
  request.responseType = "json";
  request.setRequestHeader("Accept", "application/json");
  submitButton.disabled = true;
  progressArea.hidden = false;
  progressBar.value = 0;
  progressValue.textContent = "0%";
  progressMessage.textContent = "Uploading your PDF...";

  request.upload.addEventListener("progress", (progressEvent) => {
    if (!progressEvent.lengthComputable) {
      return;
    }

    const percent = Math.round((progressEvent.loaded / progressEvent.total) * 100);
    progressBar.value = percent;
    progressValue.textContent = `${percent}%`;
    if (percent === 100) {
      progressMessage.textContent = "Arranging pages...";
    }
  });

  request.addEventListener("load", () => {
    const response = request.response;
    if (request.status < 200 || request.status >= 300) {
      statusMessage.textContent = response?.error || "The PDF could not be processed.";
      progressArea.hidden = true;
      submitButton.disabled = false;
      return;
    }

    frontPreview.src = response.preview_front_url;
    backPreview.src = response.preview_back_url;
    downloadLink.href = response.download_url;
    const duplexSets = Math.ceil(response.total_input_pages / 16);
    const setLabel = duplexSets === 1 ? "duplex set" : "duplex sets";
    const enhancementLabel = response.enhancement_enabled
      ? " · scanned-page enhancement enabled"
      : "";
    resultSummary.textContent =
      `${response.total_input_pages} input pages · ${response.total_output_pages} PDF pages · ${duplexSets} ${setLabel}${enhancementLabel}`;
    resultPanel.hidden = false;
    progressBar.value = 100;
    progressValue.textContent = "100%";
    progressMessage.textContent = "Done";
    submitButton.disabled = false;
  });

  request.addEventListener("error", () => {
    statusMessage.textContent = "A network error interrupted the upload. Please try again.";
    progressArea.hidden = true;
    submitButton.disabled = false;
  });

  request.addEventListener("timeout", () => {
    statusMessage.textContent = "The request timed out. Please try again.";
    progressArea.hidden = true;
    submitButton.disabled = false;
  });

  request.timeout = 5 * 60 * 1000;
  request.send(new FormData(form));
});
