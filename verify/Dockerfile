# One-off acceptance image for `docker compose run --rm verify`.
#
# Unlike the slim API image, the acceptance harness also drives a REAL
# Chromium against the built SPA to prove the frontend's BigInt round trip
# never routes a 4301-digit timestamp through JavaScript Number. The base
# image is Microsoft's official Playwright-for-Python image (version pinned to
# match @playwright/test in frontend/package-lock.json) and already ships
# Python 3, the `playwright` package and the Chromium browser + system deps.
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

WORKDIR /verify

# verify.py is bind-mounted at /verify:ro by docker compose; keep the image
# free of project files so it needs rebuilding only when the base changes.
CMD ["python", "/verify/verify.py"]
