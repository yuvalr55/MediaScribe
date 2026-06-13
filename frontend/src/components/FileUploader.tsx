import { useCallback, useRef, useState } from "react";
import { MAX_UPLOAD_MB } from "../api/client";

interface Props {
  disabled: boolean;
  onSelect: (files: File[]) => void;
}

export function FileUploader({ disabled, onSelect }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const handleFiles = useCallback(
    (fileList: FileList | null) => {
      if (!fileList || disabled) return;
      const files = Array.from(fileList);
      if (files.length) onSelect(files);
    },
    [disabled, onSelect]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      handleFiles(e.dataTransfer.files);
    },
    [handleFiles]
  );

  return (
    <div
      className={`dropzone ${dragging ? "dropzone--active" : ""} ${
        disabled ? "dropzone--disabled" : ""
      }`}
      onClick={() => !disabled && inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
    >
      <div className="dropzone__icon">🎙️</div>
      <p className="dropzone__title">
        Drop audio or video files here, or <span>browse</span>
      </p>
      <p className="dropzone__hint">
        MP3 · WAV · M4A · MP4 · MOV — up to {MAX_UPLOAD_MB} MB · multiple files supported
      </p>
      <input
        ref={inputRef}
        type="file"
        accept="audio/*,video/*"
        multiple
        hidden
        onChange={(e) => {
          handleFiles(e.target.files);
          e.target.value = "";
        }}
      />
    </div>
  );
}
