"""Full end-to-end pipeline test on a single video."""
import logging
logging.basicConfig(level=logging.INFO)

from pipeline import process_video

result = process_video({
    "id": "qeREwBGVig8",
    "title": "Is World War 3 Starting? | DEEP FOCUS with John Kiriakou",
    "url": "https://www.youtube.com/watch?v=qeREwBGVig8",
})
print(f"\nClips queued: {result}")
