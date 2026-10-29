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
    document.querySelectorAll('form').forEach(function(form){
      form.addEventListener('submit', function(){
        show();
        setTimeout(hide, 120000);
      });
    });
    document.querySelectorAll('input[type=file]').forEach(function(inp){
      inp.addEventListener('change', function(){
        show();
        setTimeout(hide, 60000);
      });
    });
    window.addEventListener('load', hide);
  });
})();