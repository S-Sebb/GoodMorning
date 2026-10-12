// Only the account's chosen website model is read and saved. Never reload automatically.
const modelForm = document.querySelector('#model-form');
if (modelForm) {
  const modelConfig = JSON.parse(document.querySelector('#language-config').dataset.config);
  const modelFeedback = document.querySelector('#model-feedback');
  const modelSelected = document.querySelector('#website-model');
  const t = key => typeof goodmorningT === 'function' ? goodmorningT(key) : key;
  let modelSaving = false;
  async function saveWebsiteModel(event) {
    event?.preventDefault();
    if (modelSaving) return;
    modelSaving = true;
    modelSelected.disabled = true;
    try {
      const response = await fetch('/api/model', {method:'POST',headers:{'Content-Type':'application/json','X-Briefing-CSRF':modelConfig.csrf},
        body:JSON.stringify({model:modelSelected.value}),credentials:'same-origin',cache:'no-store'});
      const result = await response.json().catch(() => ({error:t('Model could not be saved. Try again.')}));
      if (!response.ok) throw new Error(result.error || t('Model could not be saved. Try again.'));
      if (typeof result.model !== 'string' || !modelSelected.querySelector(`option[value="${result.model}"]`)) throw new Error(t('Model could not be saved. Try again.'));
      modelSelected.value = result.model; modelFeedback.textContent = t('Model saved.');
    } catch (error) { modelFeedback.textContent = error.message; }
    finally { modelSelected.disabled = false; modelSaving = false; }
  }
  modelForm.addEventListener('submit', saveWebsiteModel);
  modelSelected.addEventListener('change', saveWebsiteModel);
  document.addEventListener('website:before-refresh', event => {
    if (modelSelected.disabled) event.preventDefault();
  });
}
