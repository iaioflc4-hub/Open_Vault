// Arranque de Mermaid: dibuja los diagramas que Open_Vault genera a partir de
// los encabezados de cada captura. Se inicializa al cargar el script (y no
// dentro de DOMContentLoaded) porque Mermaid engancha su propio evento al
// cargarse: si la configuración llega después, el primer diagrama queda sin
// dibujar.
(function () {
  if (!window.mermaid) {
    return;
  }
  var prefiereOscuro =
    window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  window.mermaid.initialize({
    startOnLoad: true,
    theme: prefiereOscuro ? "dark" : "default",
    securityLevel: "strict",
  });
})();
