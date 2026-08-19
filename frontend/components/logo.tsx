import { Boxes } from "lucide-react";

export function Logo() {
  return (
    <div className="brand">
      <span className="brand__mark">
        <Boxes className="brand__glyph" aria-hidden="true" />
      </span>
      <span className="brand__label">Spinbox</span>
    </div>
  );
}
