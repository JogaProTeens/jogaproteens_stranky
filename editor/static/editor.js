// Editor behaviour: character counter, cover preview, Word-style text editor,
// saving, delete confirmation and the "is it live yet" status line.

// ---------- post list ----------

document.querySelectorAll('form[data-confirm]').forEach((form) => {
  form.addEventListener('submit', (event) => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});

const deploy = document.querySelector('.deploy[data-commit]');
if (deploy) {
  const started = Date.now();
  const check = async () => {
    let state = null;
    try {
      const response = await fetch(`/api/stav/${deploy.dataset.commit}`);
      state = (await response.json()).state;
    } catch { /* offline for a moment: try again */ }
    if (state === 'done') {
      deploy.textContent = 'Hotovo, web je aktualizovaný. ';
      if (deploy.dataset.url) {
        const link = document.createElement('a');
        link.href = deploy.dataset.url;
        link.target = '_blank';
        link.rel = 'noopener';
        link.textContent = 'Otevřít článek';
        deploy.append(link);
      }
      return;
    }
    if (state === 'failed') {
      deploy.textContent = 'Aktualizace webu se nepovedla. Dejte vědět Šimonovi.';
      deploy.classList.add('deploy-failed');
      return;
    }
    if (Date.now() - started > 10 * 60 * 1000) {
      deploy.textContent = 'Aktualizace trvá nezvykle dlouho. Zkontrolujte web později.';
      return;
    }
    setTimeout(check, 5000);
  };
  setTimeout(check, 3000);
}

// ---------- editing a post ----------

const form = document.getElementById('post-form');
if (form) {
  // Characters left in the headline
  document.querySelectorAll('[data-counter-for]').forEach((counter) => {
    const input = document.getElementById(counter.dataset.counterFor);
    const show = () => {
      const left = input.maxLength - input.value.length;
      counter.textContent = `Zbývá ${left} znaků`;
      counter.classList.toggle('counter-low', left < 20);
    };
    input.addEventListener('input', show);
    show();
  });

  // Cover preview: shows the crop that will be used
  const coverInput = document.getElementById('cover');
  const preview = document.getElementById('cover-preview');
  const shapeInputs = form.querySelectorAll('input[name="orientation"]');
  const setShape = (shape) => {
    preview.className = `cover-preview cover-preview--${shape}`;
  };
  shapeInputs.forEach((input) => input.addEventListener('change', () => setShape(input.value)));

  coverInput.addEventListener('change', () => {
    const file = coverInput.files[0];
    if (!file) return;
    document.getElementById('cover-name').textContent = file.name;
    const img = new Image();
    img.alt = '';
    img.onload = () => {
      const shape = img.naturalWidth > img.naturalHeight ? 'landscape' : 'portrait';
      form.querySelector(`input[name="orientation"][value="${shape}"]`).checked = true;
      setShape(shape);
    };
    img.onerror = () => {
      preview.replaceChildren(Object.assign(document.createElement('span'), {
        textContent: 'Náhled tu nejde zobrazit, fotka se zpracuje při uložení.',
      }));
    };
    img.src = URL.createObjectURL(file);
    preview.replaceChildren(img);
  });

  // Word-style text editor (Quill)
  const quill = new Quill('#body-editor', {
    theme: 'snow',
    placeholder: 'Sem napište text článku…',
    formats: ['header', 'bold', 'italic', 'underline', 'list', 'blockquote', 'link', 'image'],
    modules: {
      toolbar: {
        container: [
          [{ header: [2, 3, false] }],
          ['bold', 'italic', 'underline'],
          [{ list: 'ordered' }, { list: 'bullet' }],
          ['blockquote', 'link', 'image'],
          ['clean'],
        ],
        handlers: { image: pickImage },
      },
    },
  });

  // Czech tooltips for the toolbar buttons
  const titles = {
    'ql-bold': 'Tučně (Cmd+B)', 'ql-italic': 'Kurzíva (Cmd+I)', 'ql-underline': 'Podtržení (Cmd+U)',
    'ql-blockquote': 'Citát', 'ql-link': 'Odkaz', 'ql-image': 'Vložit fotku', 'ql-clean': 'Zrušit formátování',
  };
  document.querySelectorAll('.ql-toolbar button').forEach((button) => {
    const cls = [...button.classList].find((c) => titles[c]);
    if (cls) button.title = titles[cls];
    if (button.classList.contains('ql-list')) {
      button.title = button.value === 'ordered' ? 'Číslovaný seznam' : 'Odrážky';
    }
  });
  const headerPicker = document.querySelector('.ql-header.ql-picker');
  if (headerPicker) headerPicker.title = 'Styl odstavce';

  // Photos inside the text: shrink in the browser so saving stays quick
  function pickImage() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.onchange = async () => {
      const file = input.files[0];
      if (!file) return;
      try {
        const dataUrl = await shrinkImage(file, 2000);
        const range = quill.getSelection(true);
        quill.insertEmbed(range.index, 'image', dataUrl, 'user');
        quill.setSelection(range.index + 1, 0);
      } catch {
        showErrors(['Tuhle fotku prohlížeč neumí otevřít. Zkuste ji uložit jako JPG.']);
      }
    };
    input.click();
  }

  async function shrinkImage(file, maxEdge) {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, maxEdge / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', 0.9);
  }

  function dataUrlToBlob(dataUrl) {
    const [head, base64] = dataUrl.split(',');
    const type = head.match(/data:([^;]+)/)[1];
    const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
    return new Blob([bytes], { type });
  }

  // Saving
  const errorsBox = document.getElementById('errors');
  function showErrors(list) {
    errorsBox.replaceChildren(...list.map((text) => Object.assign(document.createElement('p'), { textContent: text })));
    errorsBox.hidden = false;
    errorsBox.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  let dirty = false;
  form.addEventListener('input', () => { dirty = true; });
  quill.on('text-change', () => { dirty = true; });
  window.addEventListener('beforeunload', (event) => {
    if (dirty) event.preventDefault();
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = event.submitter;
    const buttons = form.querySelectorAll('.actions button');
    const data = new FormData(form);
    data.set('action', button.value);

    // Photos pasted or inserted into the text travel as separate files
    let html = quill.getSemanticHTML();
    const sources = [...new Set([...quill.root.querySelectorAll('img')]
      .map((img) => img.getAttribute('src'))
      .filter((src) => src && src.startsWith('data:image/')))];
    sources.forEach((src, i) => {
      const key = `upload/${i}`;
      html = html.split(src).join(key);
      data.append(key, dataUrlToBlob(src), `foto-${i}`);
    });
    data.set('body', html);

    errorsBox.hidden = true;
    buttons.forEach((b) => { b.disabled = true; });
    const label = button.textContent;
    button.textContent = 'Ukládám…';
    try {
      const response = await fetch('/ulozit', { method: 'POST', body: data });
      let result;
      try { result = await response.json(); } catch { result = { ok: false }; }
      if (result.ok) {
        dirty = false;
        window.location.href = result.redirect;
        return;
      }
      showErrors(result.errors || ['Uložení se nepovedlo. Zkuste to prosím znovu.']);
    } catch {
      showErrors(['Editor teď nejde zastihnout. Zkontrolujte připojení a zkuste to znovu.']);
    }
    buttons.forEach((b) => { b.disabled = false; });
    button.textContent = label;
  });
}
