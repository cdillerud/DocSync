(function () {
    "use strict";

    var state = {
        root: null,
        contextAvailable: false,
        maxFileSizeMB: 25,
        documents: [],
        queueBusy: false
    };

    function invoke(name, args) {
        return new Promise(function (resolve, reject) {
            Microsoft.Dynamics.NAV.InvokeExtensibilityMethod(name, args, false, resolve, reject);
        });
    }

    function makeElement(tag, className, text) {
        var element = document.createElement(tag);
        if (className) {
            element.className = className;
        }
        if (text !== undefined && text !== null) {
            element.textContent = text;
        }
        return element;
    }

    function formatBytes(bytes) {
        if (!bytes) {
            return "";
        }
        if (bytes < 1024) {
            return bytes + " B";
        }
        if (bytes < 1024 * 1024) {
            return (bytes / 1024).toFixed(1) + " KB";
        }
        return (bytes / (1024 * 1024)).toFixed(1) + " MB";
    }

    function setStatus(message, isError) {
        var status = document.getElementById("gpi-rd-status");
        if (!status) {
            return;
        }
        status.textContent = message || "";
        status.className = "gpi-rd-status" + (isError ? " error" : "");
    }

    function render() {
        if (!state.root) {
            return;
        }

        state.root.innerHTML = "";

        var header = makeElement("div", "gpi-rd-header");
        header.appendChild(makeElement("div", "gpi-rd-title", "Documents"));

        var refresh = makeElement("button", "gpi-rd-refresh", "Refresh");
        refresh.type = "button";
        refresh.addEventListener("click", function () {
            invoke("RefreshRequested", []);
        });
        header.appendChild(refresh);
        state.root.appendChild(header);

        var dropZone = makeElement(
            "div",
            "gpi-rd-dropzone" + (state.contextAvailable ? "" : " disabled")
        );
        dropZone.setAttribute("role", "button");
        dropZone.setAttribute("tabindex", state.contextAvailable ? "0" : "-1");
        dropZone.appendChild(makeElement("div", "gpi-rd-drop-icon", "⇩"));
        dropZone.appendChild(makeElement("div", "gpi-rd-drop-title", "Drop files here"));
        dropZone.appendChild(
            makeElement(
                "div",
                "gpi-rd-drop-help",
                state.contextAvailable
                    ? "or click to choose files"
                    : "Save the record before attaching documents"
            )
        );

        var input = document.createElement("input");
        input.type = "file";
        input.multiple = true;
        input.className = "gpi-rd-file-input";
        input.addEventListener("change", function () {
            processFiles(Array.prototype.slice.call(input.files || []));
            input.value = "";
        });

        dropZone.appendChild(input);
        dropZone.addEventListener("click", function () {
            if (state.contextAvailable && !state.queueBusy) {
                input.click();
            }
        });
        dropZone.addEventListener("keydown", function (event) {
            if ((event.key === "Enter" || event.key === " ") &&
                state.contextAvailable &&
                !state.queueBusy) {
                event.preventDefault();
                input.click();
            }
        });
        dropZone.addEventListener("dragover", function (event) {
            if (!state.contextAvailable || state.queueBusy) {
                return;
            }
            event.preventDefault();
            dropZone.classList.add("dragging");
        });
        dropZone.addEventListener("dragleave", function () {
            dropZone.classList.remove("dragging");
        });
        dropZone.addEventListener("drop", function (event) {
            dropZone.classList.remove("dragging");
            if (!state.contextAvailable || state.queueBusy) {
                return;
            }
            event.preventDefault();
            processFiles(Array.prototype.slice.call(event.dataTransfer.files || []));
        });

        state.root.appendChild(dropZone);

        var status = makeElement("div", "gpi-rd-status");
        status.id = "gpi-rd-status";
        state.root.appendChild(status);

        var list = makeElement("div", "gpi-rd-list");
        if (!state.documents.length) {
            list.appendChild(makeElement("div", "gpi-rd-empty", "No documents are attached."));
        } else {
            state.documents.forEach(function (documentItem) {
                var row = makeElement(
                    "button",
                    "gpi-rd-document" +
                        (documentItem.status === "Uploaded" ? "" : " unavailable")
                );
                row.type = "button";
                row.disabled = documentItem.status !== "Uploaded";
                row.addEventListener("click", function () {
                    invoke("DocumentOpenRequested", [documentItem.entryNo]);
                });

                row.appendChild(
                    makeElement("div", "gpi-rd-document-name", documentItem.fileName)
                );

                var metaParts = [];
                if (documentItem.category) {
                    metaParts.push(documentItem.category);
                }
                if (documentItem.uploadedAt) {
                    metaParts.push(documentItem.uploadedAt);
                }
                if (documentItem.size) {
                    metaParts.push(formatBytes(documentItem.size));
                }
                if (documentItem.status && documentItem.status !== "Uploaded") {
                    metaParts.push(documentItem.status);
                }

                row.appendChild(
                    makeElement("div", "gpi-rd-document-meta", metaParts.join(" • "))
                );
                list.appendChild(row);
            });
        }

        state.root.appendChild(list);
    }

    function readAsDataUrl(file) {
        return new Promise(function (resolve, reject) {
            var reader = new FileReader();
            reader.onload = function () {
                resolve(reader.result);
            };
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    }

    async function uploadFile(file) {
        if (file.size > state.maxFileSizeMB * 1024 * 1024) {
            throw new Error(
                file.name + " exceeds the " + state.maxFileSizeMB + " MB upload limit."
            );
        }

        var uploadId =
            Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
        var dataUrl = await readAsDataUrl(file);
        var comma = dataUrl.indexOf(",");
        var base64 = comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl;
        var chunkSize = 60000;
        var totalChunks = Math.ceil(base64.length / chunkSize);

        await invoke("UploadStarted", [
            uploadId,
            file.name,
            file.type || "",
            file.size,
            totalChunks
        ]);

        for (var index = 0; index < totalChunks; index += 1) {
            setStatus(
                "Uploading " + file.name + " (" + (index + 1) + " of " + totalChunks + ")",
                false
            );
            await invoke("UploadChunk", [
                uploadId,
                index,
                base64.slice(index * chunkSize, (index + 1) * chunkSize)
            ]);
        }

        await invoke("UploadCompleted", [uploadId]);
    }

    async function processFiles(files) {
        if (!files.length || state.queueBusy) {
            return;
        }

        state.queueBusy = true;
        render();

        try {
            for (var index = 0; index < files.length; index += 1) {
                await uploadFile(files[index]);
            }
            setStatus(files.length + " document(s) uploaded.", false);
        } catch (error) {
            setStatus(
                error && error.message ? error.message : "The document upload failed.",
                true
            );
        } finally {
            state.queueBusy = false;
            render();
        }
    }

    window.GPIRecordDocumentsStartup = function () {
        state.root = document.getElementById("controlAddIn");
        render();
        invoke("ControlReady", []);
    };

    window.InitializeRecordDocuments = function (captionText, maxFileSizeMB) {
        state.maxFileSizeMB = maxFileSizeMB || 25;
        render();
    };

    window.SetRecordContext = function (contextAvailable) {
        state.contextAvailable = !!contextAvailable;
        render();
    };

    window.SetRecordDocuments = function (documentsJson) {
        try {
            state.documents = documentsJson ? JSON.parse(documentsJson) : [];
        } catch (error) {
            state.documents = [];
            setStatus("The document list could not be displayed.", true);
        }
        render();
    };

    window.SetRecordUploadStatus = function (statusText, isError) {
        setStatus(statusText, !!isError);
    };
})();
