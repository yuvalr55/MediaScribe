import { forwardRef, memo } from "react";
import type { SyntheticEvent } from "react";

interface Props {
  src: string;
  onTimeUpdate: (event: SyntheticEvent<HTMLAudioElement>) => void;
  onEnded: () => void;
}

export const JobAudioPlayer = memo(forwardRef<HTMLAudioElement, Props>(
  function JobAudioPlayer({ src, onTimeUpdate, onEnded }, ref) {
    return (
      <audio
        ref={ref}
        className="job-item__audio"
        src={src}
        controls
        preload="metadata"
        onTimeUpdate={onTimeUpdate}
        onEnded={onEnded}
      />
    );
  }
));
