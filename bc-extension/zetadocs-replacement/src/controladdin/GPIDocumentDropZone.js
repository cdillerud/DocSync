var gpiDropZoneState = {
    initialized: false,
    contextReady: false,
    busy: false,
    documentCount: 0,
    contextCaption: '',
    queue: []
};

function GPIInitializeDocumentDropZone() {
    if (gpiDropZoneState.initialized)
        return;

    var host = document.getElementById('controlAddIn');
    if (!host)
        return;

    host.innerHTML = '';

    var zone = document.createElement('div');
    zone.id = 'gpi-document-drop-zone';
    zone.className = 'gpi-drop-zone gpi-disabled';
    zone.setAttribute('role', 'button');
    zone.setAttribute('tabindex', '0');

    var icon = document.createElement('div');
    icon.className = 'gpi-drop-icon';
    icon.textContent = '⇩';

    var title = document.createElement('div');
    title.id = 'gpi-drop-title';
    title.className = 'gpi-drop-title';
    title.textContent = 'Save the record before adding documents';

    var subtitle = document.createElement('div');
    subtitle.id = 'gpi-drop-subtitle';
    subtitle.className = 'gpi-drop-subtitle';
    subtitle.textContent = 'Drag files here or click to browse';

    var status = document.createElement('div');
    status.id = 'gpi-drop-status';
    status.className = 'gpi-drop-status';

    var input = document.createElement('input');
    input.id = 'gpi-drop-file-input';
    input.type = 'file';
    input.multiple = true;
    input.style.display = 'none';

    zone.appendChild(icon);
    zone.appendChild(title);
    zone.appendChild(subtitle);
    zone.appendChild(status);
    zone.appendChild(input);
    host.appendChild(zone);

    zone.addEventListener('click', function () {
        if (gpiDropZoneState.contextReady && !gpiDropZoneState.busy)
            input.click();
    });

    zone.addEventListener('keydown', function (event) {
        if ((event.key === 'Enter' || event.key === ' ') && gpiDropZoneState.contextReady && !gpiDropZoneState.busy) {
            event.preventDefault();
            input.click();
        }
    });

    input.addEventListener('change', function () {
        GPIQueueFiles(input.files);
        input.value = '';
    });

    ['dragenter', 'dragover'].forEach(function (eventName) {
        zone.addEventListener(eventName, function (event) {
            event.preventDefault();
            event.stopPropagation();
            if (gpiDropZoneState.contextReady && !gpiDropZoneState.busy)
                zone.classList.add('gpi-drag-over');
        });
    });

    ['dragleave', 'drop'].forEach(function (eventName) {
        zone.addEventListener(eventName, function (event) {
            event.preventDefault();
            event.stopPropagation();
            zone.classList.remove('gpi-drag-over');
        });
    });

    zone.addEventListener('drop', function (event) {
        if (!gpiDropZoneState.contextReady || gpiDropZoneState.busy)
            return;
        GPIQueueFiles(event.dataTransfer.files);
    });

    gpiDropZoneState.initialized = true;
    GPIRenderDropZone();
}

function GPIQueueFiles(fileList) {
    if (!fileList || fileList.length === 0)
        return;

    for (var i = 0; i < fileList.length; i++)
        gpiDropZoneState.queue.push(fileList[i]);

    GPIProcessNextFile();
}

function GPIProcessNextFile() {
    if (gpiDropZoneState.busy || gpiDropZoneState.queue.length === 0)
        return;

    var file = gpiDropZoneState.queue.shift();
    var maxBytes = 8 * 1024 * 1024;

    if (file.size > maxBytes) {
        GPISetStatus(file.name + ' is larger than the 8 MB upload limit.', false);
        GPIProcessNextFile();
        return;
    }

    if (GPIIsBlockedFile(file.name)) {
        GPISetStatus(file.name + ' is a blocked file type.', false);
        GPIProcessNextFile();
        return;
    }

    gpiDropZoneState.busy = true;
    GPISetStatus('Uploading ' + file.name + '...', true);
    GPIRenderDropZone();

    var reader = new FileReader();
    reader.onload = function (event) {
        var result = event.target.result || '';
        var commaIndex = result.indexOf(',');
        var base64Content = commaIndex >= 0 ? result.substring(commaIndex + 1) : result;
        var contentType = file.type || 'application/octet-stream';

        Microsoft.Dynamics.NAV.InvokeExtensibilityMethod(
            'FileDropped',
            [file.name, contentType, base64Content, file.size],
            false,
            function () {
                gpiDropZoneState.busy = false;
                GPIRenderDropZone();
                GPIProcessNextFile();
            }
        );
    };

    reader.onerror = function () {
        gpiDropZoneState.busy = false;
        GPISetStatus('The browser could not read ' + file.name + '.', false);
        GPIRenderDropZone();
        GPIProcessNextFile();
    };

    reader.readAsDataURL(file);
}

function GPIIsBlockedFile(fileName) {
    var blocked = ['.exe', '.dll', '.bat', '.cmd', '.com', '.msi', '.ps1', '.scr', '.vbs', '.js'];
    var lowerName = (fileName || '').toLowerCase();
    return blocked.some(function (extension) {
        return lowerName.endsWith(extension);
    });
}

function SetContext(contextCaption, documentCount, isContextReady) {
    gpiDropZoneState.contextCaption = contextCaption || '';
    gpiDropZoneState.documentCount = documentCount || 0;
    gpiDropZoneState.contextReady = !!isContextReady;
    GPIRenderDropZone();
}

function SetBusy(isBusy) {
    gpiDropZoneState.busy = !!isBusy;
    GPIRenderDropZone();
}

function NotifyResult(isSuccess, messageText, documentCount) {
    gpiDropZoneState.busy = false;
    gpiDropZoneState.documentCount = documentCount || 0;
    GPISetStatus(messageText || '', !!isSuccess);
    GPIRenderDropZone();
}

function GPISetStatus(messageText, isSuccess) {
    var status = document.getElementById('gpi-drop-status');
    if (!status)
        return;
    status.textContent = messageText || '';
    status.className = isSuccess ? 'gpi-drop-status gpi-success' : 'gpi-drop-status gpi-error';
}

function GPIRenderDropZone() {
    if (!gpiDropZoneState.initialized)
        return;

    var zone = document.getElementById('gpi-document-drop-zone');
    var title = document.getElementById('gpi-drop-title');
    var subtitle = document.getElementById('gpi-drop-subtitle');

    if (!zone || !title || !subtitle)
        return;

    zone.classList.toggle('gpi-disabled', !gpiDropZoneState.contextReady || gpiDropZoneState.busy);
    zone.classList.toggle('gpi-busy', gpiDropZoneState.busy);

    if (!gpiDropZoneState.contextReady) {
        title.textContent = 'Save the record before adding documents';
        subtitle.textContent = 'Drag files here or click to browse';
        return;
    }

    title.textContent = gpiDropZoneState.contextCaption || 'GPI Documents';
    subtitle.textContent = gpiDropZoneState.documentCount +
        (gpiDropZoneState.documentCount === 1 ? ' linked document' : ' linked documents') +
        ' · Drag files here or click to browse';
}
