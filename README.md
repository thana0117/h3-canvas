# H3 Canvas

A canvas for building the **scope material** of a video project: characters, scenes and props.
You run it on your **Mac**. Each card generates stills with **Qwen Image 2.1** on the **home PC's ComfyUI**,
and every result is copied back to the laptop.

```
MacBook (H3 Canvas: projects, assets, history)  ──Tailscale──▶  Home PC (ComfyUI :8188, GPU only)
```

- **The laptop holds everything:** projects, every variant, prompts and seeds, and which image is approved. Files live in `~/H3Canvas`.
- **The PC stays clean:** `SaveImage` is swapped for `PreviewImage`, so renders land in ComfyUI's `temp/`, which ComfyUI wipes on restart. Finished jobs are also removed from ComfyUI's history.
- **It's polite to the GPU:** while anything else is in ComfyUI's queue (for example a Studio video batch), stills wait until the queue is empty. You can turn this off in Settings.
- **It survives sleep and wifi drops:** jobs already on the PC keep rendering. When the laptop reconnects, the app collects the results. If the PC is offline, jobs wait and are sent automatically once it's reachable.

## 1. One-time setup: connect the Mac to the PC (Tailscale)

ComfyUI has no password, so **never port-forward it to the internet**. Tailscale gives both machines a private network that works from anywhere.

1. Install Tailscale on **both** machines (https://tailscale.com/download) and sign in to the same account on each.
2. On the PC, note its Tailscale name (for example `home-pc`) or its `100.x.y.z` IP from the Tailscale menu.
3. Make ComfyUI listen on the Tailscale address as well as localhost. In the portable build's `run_nvidia_gpu.bat`, add `--listen`:
   ```bat
   .\python_embeded\python.exe -s ComfyUI\main.py --windows-standalone-build --listen 127.0.0.1,100.x.y.z
   ```
   `--listen 0.0.0.0` also works, but it exposes ComfyUI to everything on your home LAN too.
   If you start ComfyUI through Short Film Studio's `--start-comfy`, the same flag has to reach that launch command.
4. If Windows Firewall asks, allow Python on **private** networks. Or allow inbound TCP 8188 for the Tailscale interface only.
5. On the Mac, check the connection: `curl http://home-pc:8188/system_stats` should return JSON.

## 2. Run it on the Mac

```bash
brew install python node        # once, if missing
git clone https://github.com/thana0117/h3-canvas && cd h3-canvas
./start.sh --comfy http://home-pc:8188
```

The browser opens at http://127.0.0.1:5180. After the first run, `./start.sh` alone is enough because the URL is saved. You can also change it any time in **Settings**, where **Save & test** shows the GPU, free VRAM and queue.

To try the UI without touching the PC, run `./start.sh --demo`. It uses a fake ComfyUI and keeps its data in `~/H3Canvas-demo`.

## Using it

1. **+ Character / + Scene / + Prop** adds a card to the canvas. Drag cards by their header.
2. Name the card and describe it, pick an aspect ratio and the number of variants, then click **Generate**.
3. Variants appear under the image. Click one to open it full size, then use **Approve as reference** to make it that card's approved still (★).
4. **Library** (top right) lists the approved images of the project, or all of them filtered by type.
5. **Settings > Project** holds the project-wide look and style line, the negative prompt and the prompt templates per card type. These are applied to every generation.

## Workflows

The built-in workflow is `workflows/qwen_image_21_t2i.json`. It's the exact Qwen Image 2.1 graph that works on the PC:
`Q2.1\qwen_image_2.1_int8_convrot`, `qwen3vl_8b_int8_convrot`, `TextEncodeQwenImage21`, 30 steps, cfg 1, `er_sde`.

To use another graph, export it from ComfyUI with **Workflow > Export (API)** and put it in `~/H3Canvas/workflows/`. Then pick it in Settings.
The app finds the prompt, negative, seed, size and LoadImage inputs on its own, and Settings shows what it found.
If the guess is wrong, add `<name>.map.json` next to the workflow:

```json
{ "prompt": ["4", "prompt"], "negative": ["4", "negative_prompt"], "seed": ["6", "seed"],
  "width": ["5", "width"], "height": ["5", "height"], "images": [["10", "image"]] }
```

## Roadmap

- **Phase 1 (this version):** canvas, character/scene/prop cards, Qwen Image 2.1 generation, a variant history kept on the laptop, approval, library, wait-for-idle.
- **Phase 2:** identity-consistent variants (Qwen edit using the approved still as a reference), outfit variants per character, and a crop tool for face and body plates.
- **Phase 3:** **Send to Short Film Studio.** Upload approved plates into ComfyUI `input/<project>/` and bind them as `referenceImages` slots in a Studio `prompt.json` (`/api/projects/save`). Then pull finished clips back to the laptop and remove them from the PC.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt pytest
cd backend && ../.venv/bin/python -m pytest          # backend tests incl. end-to-end against the fake ComfyUI
cd frontend && npm install && npm run dev            # UI with hot reload (proxies to the backend on :5180)
```
