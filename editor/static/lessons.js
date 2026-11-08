// Lekce page: lesson cards (with a small text editor for the note) and the
// photo gallery. Everything is sent in one go when Petra clicks Uložit.

(() => {      // own scope: editor.js on the same page also has a `form`
const form = document.getElementById('lessons-form');
if (form) {
  const data = JSON.parse(document.getElementById('schedule-data').textContent);
  const lessonList = document.getElementById('lesson-list');
  const galleryList = document.getElementById('gallery-list');
  const lessonTemplate = document.getElementById('lesson-template');
  const photoTemplate = document.getElementById('photo-template');
  const errorsBox = document.getElementById('errors');
  const editors = new WeakMap();      // lesson <li> -> its Quill
  const photos = new WeakMap();       // photo <li> -> {file} or {blob}
  let dirty = false;

  // ---------- lessons ----------

  function addLesson(lesson = {}) {
    const item = lessonTemplate.content.firstElementChild.cloneNode(true);
    item.querySelectorAll('[data-key]').forEach((input) => { input.value = lesson[input.dataset.key] || ''; });
    const box = item.querySelector('.note-editor');
    box.innerHTML = lesson.note || '';               // already cleaned by the server
    lessonList.append(item);
    const quill = new Quill(box, {
      theme: 'snow',
      placeholder: 'Třeba: Na lekce se hlaste přes web DůmUm.',
      formats: ['bold', 'italic', 'link'],
      modules: { toolbar: [['bold', 'italic', 'link'], ['clean']] },
    });
    quill.on('text-change', () => { dirty = true; });
    const titles = { 'ql-bold': 'Tučně', 'ql-italic': 'Kurzíva', 'ql-link': 'Odkaz', 'ql-clean': 'Zrušit formátování' };
    item.querySelectorAll('.ql-toolbar button').forEach((button) => {
      const cls = [...button.classList].find((c) => titles[c]);
      if (cls) button.title = titles[cls];
    });
    editors.set(item, quill);
    renumber();
    return item;
  }

  function renumber() {
    [...lessonList.children].forEach((item, i) => {
      item.querySelector('.lesson-number').textContent = `Lekce ${i + 1}`;
    });
  }

  document.getElementById('add-lesson').addEventListener('click', () => {
    const item = addLesson();
    dirty = true;
    item.querySelector('input').focus();
  });

  // Links without https:// ("dumum.cz") would lead nowhere: add it
  function fixLinks(html) {
    const box = document.createElement('div');
    box.innerHTML = html;
    box.querySelectorAll('a[href]').forEach((a) => {
      const href = a.getAttribute('href').trim();
      if (/^[\w.+-]+@[\w-]+\.[\w.-]+$/.test(href)) a.setAttribute('href', `mailto:${href}`);
      else if (!/^(https?:|mailto:|tel:|#|\/)/i.test(href)) a.setAttribute('href', `https://${href}`);
    });
    return box.innerHTML;
  }

  // ---------- gallery ----------

  function addPhoto(source, alt = '') {
    const item = photoTemplate.content.firstElementChild.cloneNode(true);
    item.querySelector('[data-key="alt"]').value = alt;
    const thumb = item.querySelector('.photo-thumb');
    const img = new Image();
    img.alt = '';
    img.onerror = () => {
      thumb.replaceChildren(Object.assign(document.createElement('span'), {
        textContent: 'Náhled nejde zobrazit, fotka se zpracuje při uložení.',
      }));
    };
    img.src = source.file ? `/lekce-foto/${encodeURIComponent(source.file)}` : URL.createObjectURL(source.blob);
    thumb.append(img);
    photos.set(item, source);
    galleryList.append(item);
    return item;
  }

  // Phone photos are big: shrink them in the browser so saving stays quick
  async function shrink(file) {
    try {
      const bitmap = await createImageBitmap(file);
      const scale = Math.min(1, 2400 / Math.max(bitmap.width, bitmap.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(bitmap.width * scale);
      canvas.height = Math.round(bitmap.height * scale);
      canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      return await new Promise((resolve) => canvas.toBlob((blob) => resolve(blob || file), 'image/jpeg', 0.9));
    } catch {
      return file;                    // e.g. HEIC: the server converts it
    }
  }

  const picker = document.getElementById('gallery-add');
  picker.addEventListener('change', async () => {
    const files = [...picker.files];
    picker.value = '';
    let first = null;
    for (const file of files) {
      const item = addPhoto({ blob: await shrink(file) });
      first = first || item;
    }
    if (first) {
      dirty = true;
      first.querySelector('input').focus();
    }
  });

  // ---------- move and remove (both lists) ----------

  form.addEventListener('click', (event) => {
    const button = event.target.closest('[data-move], [data-remove]');
    if (!button) return;
    const item = button.closest('li');
    if (button.hasAttribute('data-remove')) {
      item.remove();
    } else if (button.dataset.move === '-1' && item.previousElementSibling) {
      item.previousElementSibling.before(item);
    } else if (button.dataset.move === '1' && item.nextElementSibling) {
      item.nextElementSibling.after(item);
    }
    dirty = true;
    renumber();
  });

  form.addEventListener('input', () => { dirty = true; });
  window.addEventListener('beforeunload', (event) => {
    if (dirty) event.preventDefault();
  });

  data.lessons.forEach((lesson) => addLesson(lesson));
  data.gallery.forEach((photo) => addPhoto({ file: photo.file }, photo.alt));

  // ---------- saving ----------

  function showErrors(list) {
    errorsBox.replaceChildren(...list.map((text) => Object.assign(document.createElement('p'), { textContent: text })));
    errorsBox.hidden = false;
    errorsBox.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const body = new FormData();
    const payload = {
      intro: document.getElementById('intro').value,
      lessons: [...lessonList.children].map((item) => {
        const lesson = {};
        item.querySelectorAll('[data-key]').forEach((input) => { lesson[input.dataset.key] = input.value; });
        const quill = editors.get(item);
        lesson.note = quill.getText().trim() ? fixLinks(quill.getSemanticHTML()) : '';
        return lesson;
      }),
      gallery: [...galleryList.children].map((item, i) => {
        const source = photos.get(item);
        const photo = { alt: item.querySelector('[data-key="alt"]').value };
        if (source.file) {
          photo.file = source.file;
        } else {
          photo.upload = `upload/${i}`;
          body.append(photo.upload, source.blob, `foto-${i}.jpg`);
        }
        return photo;
      }),
    };
    body.set('data', JSON.stringify(payload));

    const button = form.querySelector('.actions button');
    errorsBox.hidden = true;
    button.disabled = true;
    const label = button.textContent;
    button.textContent = 'Ukládám…';
    try {
      const response = await fetch('/lekce/ulozit', { method: 'POST', body });
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
    button.disabled = false;
    button.textContent = label;
  });
}
})();
