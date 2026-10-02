# Fieldwork

A multimodal asset workspace with a browser frontend, FastAPI, PostgreSQL, Redis,
and OpenSearch. Seven pinned Hugging Face models run real CPU inference for text,
images, and audio. Application and inference code adapted from Chris Levy’s
[modal-native-test-stack-poc](https://github.com/DrChrisLevy/modal-native-test-stack-poc),
under the included MIT license.

Use `./run up` or `./run up remote NAME` from the repository root. Initial setup
downloads model weights once; subsequent environments reuse them. Open the printed
URL for the frontend, or `/docs` for the API. Use `./run test [remote NAME]` for
the real model, service, API, and end-to-end tests plus Ruff.
