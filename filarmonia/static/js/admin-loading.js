(function(){
  document.addEventListener('DOMContentLoaded', function(){
    var overlay = document.getElementById('loading-overlay');
    if (!overlay){
      overlay = document.createElement('div');
      overlay.className = 'loading-overlay';
      overlay.id = 'loading-overlay';
      overlay.setAttribute('aria-hidden','true');
      var spinner = document.createElement('div');
      spinner.className = 'loading-spinner';
      overlay.appendChild(spinner);
      document.body.appendChild(overlay);
    }
    function show(){ overlay.classList.add('is-active'); overlay.setAttribute('aria-hidden','false'); }
    function hide(){ overlay.classList.remove('is-active'); overlay.setAttribute('aria-hidden','true'); }

    /* Считаем выбранные файлы формы для решения, показывать ли спиннер. */
    function countFiles(form){
      var count = 0;
      form.querySelectorAll('input[type=file]').forEach(function(inp){
        if (inp.files && inp.files.length) count += inp.files.length;
      });
      return count;
    }

    /* Спиннер — только при отправке формы с выбранным файлом. */
    document.querySelectorAll('form').forEach(function(form){
      form.addEventListener('submit', function(){
        if (countFiles(form) > 0){
          show();
        }
      });
    });

    /* Скрываем при загрузке страницы (вкл. навигацию через сохранённый стейт). */
    window.addEventListener('load', hide);
  });
})();