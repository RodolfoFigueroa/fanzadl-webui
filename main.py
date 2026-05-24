import sys

import uvicorn

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    uvicorn.run("fanzadl_webui.app:app", host="0.0.0.0", port=8000, reload=False)
