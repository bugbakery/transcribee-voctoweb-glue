
import io
import webvtt


def format_subtitle_vtt(vtt: str) -> str:
    captions: list[webvtt.Caption] = []
    current_caption: webvtt.Caption | None = None
    for caption in webvtt.read_buffer(io.StringIO(vtt)):
        caption: webvtt.Caption

        if current_caption is None:
            current_caption = caption
            continue

        if len(current_caption.text) + len(caption.text) < 100:
            current_caption = _merge_captions(current_caption, caption)
        else:
            line = ""
            lines = []
            for word in current_caption.text.split(" "):
                if len(line) + len(word) > 60 and line != "":
                    lines.append(line)
                    line = word
                else:
                    line += " " + word

            lines.append(line)

            captions.append(webvtt.Caption(
                start=current_caption.start,
                end=current_caption.end,
                text="\n".join(lines).strip(),
            ))

            current_caption = caption

    output_stream = io.StringIO()
    processed_vtt = webvtt.WebVTT(captions = captions)
    processed_vtt.write(output_stream, format="vtt")

    return output_stream.getvalue()

def _merge_captions(cap1: webvtt.Caption, cap2: webvtt.Caption):
    return webvtt.Caption(
        start=min(cap1.start, cap2.start),
        end=max(cap1.end, cap2.end),
        text=cap1.raw_text + cap2.raw_text,
    )
