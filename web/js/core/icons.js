// Icon markup for the Lucide sprite in web/index.html.
// Geometry lives only in the sprite; this helper builds the <svg> wrapper.

export function icon(name, className, strokeWidth) {
  return "<svg" + (className ? ' class="' + className + '"' : "") +
    ' viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="' +
    (strokeWidth || 1.6) + '" stroke-linecap="round" stroke-linejoin="round"' +
    ' aria-hidden="true"><use href="#i-' + name + '"></use></svg>';
}
