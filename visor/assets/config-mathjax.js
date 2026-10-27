// Configuración de MathJax para la vista web.
// Solo se aceptan los delimitadores que emite el traductor del visor (\\( \\) y
// \\[ \\]), nunca el signo de pesos: así un precio como "$340.000" no se
// interpreta como una fórmula.
window.MathJax = {
  tex: {
    inlineMath: [["\\(", "\\)"]],
    displayMath: [["\\[", "\\]"]],
    processEscapes: true,
  },
  options: {
    skipHtmlTags: ["script", "noscript", "style", "textarea", "pre", "code"],
  },
};
