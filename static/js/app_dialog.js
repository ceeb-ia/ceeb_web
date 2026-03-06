(function () {
  'use strict';

  if (window.showAlert && window.showConfirm && window.showPrompt) {
    return;
  }

  var modalEl = null;
  var initialized = false;
  var state = null;
  var readyAtTs = 0;
  var dialogQueue = Promise.resolve();

  function hasBootstrapModal() {
    return !!(window.jQuery && window.jQuery.fn && window.jQuery.fn.modal);
  }

  function ensureModal() {
    if (modalEl) return modalEl;

    var wrapper = document.createElement('div');
    wrapper.innerHTML = [
      '<div class="modal fade" id="appDialogModal" tabindex="-1" aria-hidden="true">',
      '  <div class="modal-dialog modal-dialog-centered">',
      '    <div class="modal-content">',
      '      <div class="modal-header">',
      '        <h5 class="modal-title" id="appDialogTitle">Missatge</h5>',
      '        <button type="button" class="close" data-dismiss="modal" aria-label="Tancar">',
      '          <span aria-hidden="true">&times;</span>',
      '        </button>',
      '      </div>',
      '      <div class="modal-body">',
      '        <p id="appDialogMessage" class="mb-0"></p>',
      '        <input id="appDialogInput" class="form-control mt-3" type="text" style="display:none;" />',
      '      </div>',
      '      <div class="modal-footer">',
      '        <button id="appDialogCancel" type="button" class="btn btn-outline-secondary" style="display:none;" data-dismiss="modal">Cancel&#183;lar</button>',
      '        <button id="appDialogOk" type="button" class="btn btn-primary">Acceptar</button>',
      '      </div>',
      '    </div>',
      '  </div>',
      '</div>'
    ].join('');

    modalEl = wrapper.firstElementChild;
    document.body.appendChild(modalEl);
    bindEvents();
    return modalEl;
  }

  function bindEvents() {
    if (initialized || !modalEl) return;

    var okBtn = modalEl.querySelector('#appDialogOk');
    var cancelBtn = modalEl.querySelector('#appDialogCancel');
    var inputEl = modalEl.querySelector('#appDialogInput');

    function resolveAndHide(value) {
      if (!state || state.resolved) return;
      state.hasCloseValue = true;
      state.closeValue = value;
      if (hasBootstrapModal()) {
        window.jQuery(modalEl).modal('hide');
      }
    }

    okBtn.addEventListener('click', function () {
      if (Date.now() < readyAtTs) return;
      if (!state) return;
      if (state.mode === 'prompt') {
        resolveAndHide(inputEl.value);
        return;
      }
      if (state.mode === 'confirm') {
        resolveAndHide(true);
        return;
      }
      resolveAndHide(undefined);
    });

    cancelBtn.addEventListener('click', function () {
      if (Date.now() < readyAtTs) return;
      if (!state) return;
      if (state.mode === 'confirm') {
        resolveAndHide(false);
        return;
      }
      if (state.mode === 'prompt') {
        resolveAndHide(null);
        return;
      }
      resolveAndHide(undefined);
    });

    modalEl.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' && state && state.mode === 'prompt') {
        ev.preventDefault();
        resolveAndHide(inputEl.value);
      }
    });

    if (hasBootstrapModal()) {
      window.jQuery(modalEl).on('hidden.bs.modal', function () {
        if (!state) return;

        var result;
        if (state.hasCloseValue) {
          result = state.closeValue;
        } else if (state.mode === 'confirm') {
          result = false;
        } else if (state.mode === 'prompt') {
          result = null;
        } else {
          result = undefined;
        }
        state.resolved = true;
        state.resolve(result);
        state = null;
      });
    }

    initialized = true;
  }

  function showDialog(options) {
    if (!hasBootstrapModal()) {
      if (options.mode === 'confirm') {
        return Promise.resolve(window.confirm(options.message));
      }
      if (options.mode === 'prompt') {
        return Promise.resolve(window.prompt(options.message, options.defaultValue || ''));
      }
      window.alert(options.message);
      return Promise.resolve();
    }

    var el = ensureModal();
    var titleEl = el.querySelector('#appDialogTitle');
    var messageEl = el.querySelector('#appDialogMessage');
    var inputEl = el.querySelector('#appDialogInput');
    var cancelBtn = el.querySelector('#appDialogCancel');

    titleEl.textContent = options.title || 'Missatge';
    messageEl.textContent = options.message || '';

    if (options.mode === 'prompt') {
      inputEl.style.display = '';
      inputEl.value = options.defaultValue || '';
      inputEl.placeholder = options.placeholder || '';
      cancelBtn.style.display = '';
      cancelBtn.textContent = options.cancelText || 'Cancel\u00B7lar';
    } else if (options.mode === 'confirm') {
      inputEl.style.display = 'none';
      inputEl.value = '';
      inputEl.placeholder = '';
      cancelBtn.style.display = '';
      cancelBtn.textContent = options.cancelText || 'Cancel\u00B7lar';
    } else {
      inputEl.style.display = 'none';
      inputEl.value = '';
      inputEl.placeholder = '';
      cancelBtn.style.display = 'none';
    }

    return new Promise(function (resolve) {
      state = {
        mode: options.mode,
        resolve: resolve,
        resolved: false,
        hasCloseValue: false,
        closeValue: undefined
      };
      readyAtTs = Date.now() + 200;

      window.jQuery(el).modal({
        backdrop: 'static',
        keyboard: true,
        show: true
      });

      setTimeout(function () {
        if (options.mode === 'prompt') {
          inputEl.focus();
          inputEl.select();
        }
      }, 0);
    });
  }

  function enqueueDialog(options) {
    dialogQueue = dialogQueue.then(function () {
      return showDialog(options);
    }, function () {
      return showDialog(options);
    });
    return dialogQueue;
  }

  window.showAlert = function (message, title) {
    return enqueueDialog({
      mode: 'alert',
      title: title || 'Missatge',
      message: String(message || '')
    });
  };

  window.showConfirm = function (message, title) {
    return enqueueDialog({
      mode: 'confirm',
      title: title || 'Confirmacio',
      message: String(message || '')
    });
  };

  window.showPrompt = function (message, defaultValue, title) {
    return enqueueDialog({
      mode: 'prompt',
      title: title || 'Introdueix un valor',
      message: String(message || ''),
      defaultValue: defaultValue == null ? '' : String(defaultValue)
    });
  };
})();
