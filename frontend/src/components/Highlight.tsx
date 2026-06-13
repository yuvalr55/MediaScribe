import { memo, useMemo } from "react";

interface Props {
  text: string;
  terms: string[];
}

export const Highlight = memo(function Highlight({ text, terms }: Props) {
  const parts = useMemo(() => {
    if (!terms.length) return null;
    const pattern = terms
      .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
      .join("|");
    const re = new RegExp(`(${pattern})`, "gi");
    return { re, parts: text.split(re) };
  }, [text, terms]);

  if (!parts) return <>{text}</>;

  const { re, parts: segments } = parts;
  return (
    <>
      {segments.map((part, i) => {
        re.lastIndex = 0;
        return re.test(part)
          ? <mark key={i} className="search-highlight">{part}</mark>
          : part;
      })}
    </>
  );
});
