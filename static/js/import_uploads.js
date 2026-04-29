(() => {
  function getCookie(name) {
    const cookies = document.cookie ? document.cookie.split(";") : [];
    const prefix = `${name}=`;
    for (const cookie of cookies) {
      const trimmed = cookie.trim();
      if (trimmed.startsWith(prefix)) {
        return decodeURIComponent(trimmed.slice(prefix.length));
      }
    }
    return "";
  }

  function csrfToken() {
    const meta = document.querySelector("meta[name='csrf-token']");
    if (meta && meta.content) {
      return meta.content;
    }
    return getCookie("csrftoken");
  }

  function uploadUrl(template, uploadId) {
    return template.replace("__upload_id__", uploadId).replace("{upload_id}", uploadId);
  }

  async function parseJsonResponse(response) {
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || `Upload request failed with ${response.status}`);
    }
    return payload;
  }

  async function postJson(url, payload) {
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
      },
      body: JSON.stringify(payload),
    });
    return parseJsonResponse(response);
  }

  async function postChunk(url, chunkIndex, chunkBlob) {
    const formData = new FormData();
    formData.append("chunk_index", String(chunkIndex));
    formData.append("chunk", chunkBlob, `${chunkIndex}.part`);

    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Accept": "application/json",
        "X-CSRFToken": csrfToken(),
      },
      body: formData,
    });
    return parseJsonResponse(response);
  }

  async function retry(operation, retryCount) {
    let lastError = null;
    for (let attempt = 0; attempt <= retryCount; attempt += 1) {
      try {
        return await operation();
      } catch (error) {
        lastError = error;
      }
    }
    throw lastError;
  }

  async function uploadFile(options) {
    const file = options.file;
    const retryCount = options.retryCount ?? 2;
    const onProgress = options.onProgress || (() => {});
    const startPayload = await postJson(options.startUrl, {
      filename: file.name,
      size_bytes: file.size,
      total_chunks: Math.ceil(file.size / options.chunkSizeBytes),
    });

    const uploadId = startPayload.upload_id;
    const chunkSizeBytes = startPayload.chunk_size_bytes || options.chunkSizeBytes;
    const totalChunks = Math.ceil(file.size / chunkSizeBytes);

    for (let chunkIndex = 0; chunkIndex < totalChunks; chunkIndex += 1) {
      const start = chunkIndex * chunkSizeBytes;
      const end = Math.min(start + chunkSizeBytes, file.size);
      const chunkBlob = file.slice(start, end);
      const chunkUrl = uploadUrl(options.chunkUrlTemplate, uploadId);

      await retry(() => postChunk(chunkUrl, chunkIndex, chunkBlob), retryCount);
      onProgress({
        uploadId,
        chunkIndex,
        totalChunks,
        uploadedChunks: chunkIndex + 1,
        percent: Math.round(((chunkIndex + 1) / totalChunks) * 1000) / 10,
      });
    }

    return postJson(uploadUrl(options.completeUrlTemplate, uploadId), {});
  }

  function bindUploadForms() {
    const forms = Array.from(document.querySelectorAll("[data-import-upload-form]"));
    forms.forEach((form) => {
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const fileInput = form.querySelector("[data-import-upload-file]");
        const progress = form.querySelector("[data-import-upload-progress]");
        const status = form.querySelector("[data-import-upload-status]");
        const file = fileInput && fileInput.files ? fileInput.files[0] : null;
        if (!file) {
          if (status) {
            status.textContent = "Choose a zip file first.";
          }
          return;
        }

        try {
          if (status) {
            status.textContent = "Uploading";
          }
          await uploadFile({
            file,
            startUrl: form.dataset.uploadStartUrl,
            chunkUrlTemplate: form.dataset.uploadChunkUrlTemplate,
            completeUrlTemplate: form.dataset.uploadCompleteUrlTemplate,
            chunkSizeBytes: Number.parseInt(form.dataset.uploadChunkSizeBytes || "8388608", 10),
            onProgress: ({ percent }) => {
              if (progress) {
                progress.value = percent;
              }
            },
          });
          if (status) {
            status.textContent = "Received";
          }
        } catch (error) {
          if (status) {
            status.textContent = error.message;
          }
        }
      });
    });
  }

  window.HomoRepeatImportUploads = {
    uploadFile,
    csrfToken,
  };

  document.addEventListener("DOMContentLoaded", bindUploadForms);
})();
