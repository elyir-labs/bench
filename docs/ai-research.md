# AI in Elyir Bench: first look (15 October 2026)

The question: what AI options there are, and whether AI can run on the Bench at home or has to be in the cloud.
Nothing is decided; this is the research and a recommendation to start from.

## What runs where

**On a Pi 5, CPU only**
- Small object detectors at 640 px: about 7 to 15 frames a second (YOLO11n 6.8 fps ONNX, YOLO26n 67 ms with NCNN).
  Obico checks one frame every 30 to 60 s, so watching prints needs a tiny fraction of that.
  [Ultralytics benchmarks](https://docs.ultralytics.com/guides/raspberry-pi)
- Small LLMs (Ollama, Q4_K_M): Gemma 3 1B 11.5 tok/s, Llama 3.2 1B 11.2, Qwen 2.5 3B 5.2, Llama 3.2 3B 4.7 (about 4.7 GB
  of memory). Short phrasing works; real troubleshooting doesn't.
  [source](https://stratospherelinuxips.readthedocs.io/en/develop/immune/research_rpi_llm_performance.html)
- Vision-language (Moondream): 0.5B about 8 to 10 s per image, 2B about 22 to 25 s; needs 8 GB.
  [Core Electronics](https://core-electronics.com.au/guides/getting-started-with-moondream-on-the-pi-5-human-like-computer-vision/)

**Accelerators** (all Pi 5 only; none fit a Pi 4, which is what the Bench Box is today)
- AI HAT+ 13 TOPS (Hailo-8L) $70, 26 TOPS (Hailo-8) $110.
  [Tom's Hardware](https://tomshardware.com/raspberry-pi/raspberry-pi-release-higher-performance-ai-hat-13-and-26-tops-variants)
- AI HAT+ 2 (Hailo-10H, 40 TOPS INT4, 8 GB of its own), $130, January 2026, LLMs of 1 to 1.5B. Jeff Geerling: the Pi 5's
  own CPU beats it on most LLMs; YOLO about 30 fps (about 10x the CPU); a vision model and an LLM together crashed.
  [Raspberry Pi](https://www.raspberrypi.com/news/introducing-the-raspberry-pi-ai-hat-plus-2-generative-ai-on-raspberry-pi-5/),
  [Geerling](https://jeffgeerling.com/blog/2026/raspberry-pi-ai-hat-2). Not worth it for us.
- AI Camera (Sony IMX500) $70: detection on the sensor itself, about 30 fps MobileNet-SSD. Worth a look for a Bench camera.
  [Raspberry Pi](https://www.raspberrypi.com/news/raspberry-pi-ai-camera-on-sale-now/)

**Cloud**: Claude Haiku 5.5 is $0.10 / $0.50 per million tokens in / out, so a troubleshooting answer (about 2k in, 500
out) is about $0.0005. [Pricing](https://platform.claude.com/docs/en/about-claude/pricing)

## Print-failure detection today

- Obico (The Spaghetti Detective): server AGPL-3.0; one-class Darknet YOLO at 416 px, weights about 200 MB downloaded
  from obico.io with no license of their own stated, so treat them as AGPL or unlicensed. Its docs say a Pi is too weak
  for their model. [repo](https://github.com/TheSpaghettiDetective/obico-server),
  [hardware](https://obico.io/docs/server-guides/hardware-requirements)
- Bambu: X1 has micro-lidar first-layer scans and AI spaghetti detection; H2D a nozzle camera for clumping, air printing,
  spaghetti (off above 85 °C; owners report false positives).
  [wiki](https://wiki.bambulab.com/en/h2/manual/intelligent-detection)
- PrintWatch: cloud only, OctoPrint only, $9 a month per printer (2022).
- Open data: CAXTON (Cambridge), 1.27 million nozzle-camera images labeled with print parameters, not spaghetti; license
  not confirmed. [repository](https://www.repository.cam.ac.uk/items/6d77cd6d-8569-4bf4-9d5f-311ad2a49ac8/full)

## Licensing (docs/licensing.md applies)

- Ultralytics YOLO (v8, 11, 26): AGPL-3.0 or a paid Enterprise license. Avoid: it would close the relicensing door.
- Apache-2.0: YOLOX, RT-DETR (Baidu's own repository, not the copy inside Ultralytics), D-FINE, RF-DETR. Check each
  LICENSE file before use. MobileNet-SSD and EfficientDet are Apache-2.0 too (not rechecked).
- Obico's weights: don't use.

## Recommendation

Both, each where it fits:

| Idea | Where | Why |
|---|---|---|
| Watch prints: spaghetti, a part off the bed, then pause and push | Bench (Pi 5) | the camera never leaves the house; offline; free |
| "Is the bed clear?" before the queue's next print | Bench | automates It's clear |
| First-layer look from the camera | Bench | next to the first-layer work |
| "Why did it stop?" in plain words from logs and history | Cloud, in Bench Cloud | needs a big model; cheap per answer |
| Settings advice, the shelf searched in words | Cloud | same |

Our own detector, trained on an Apache-2.0 architecture. The long pole is pictures: start keeping camera frames from our
own printers, then testers who opt in. The Bench Box moves to a Pi 5 (the housing already is one).

Next steps, none started: time an Apache detector on Workshop's camera frames (Pi 5, CPU and power); start keeping frames;
draw what watching looks like (pause or tell, a false alarm); a cloud "why did it stop?" spike with Haiku over
klippy.log on staging.
