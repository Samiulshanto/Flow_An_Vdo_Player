<div align="center">
<img src="https://capsule-render.vercel.app/api?type=waving&height=175&color=000000&text=flow~&fontColor=ffffff&fontSize=76&fontAlignY=38&animation=fadeIn&desc=a%20small%20player%20that%20stays%20out%20of%20your%20way&descSize=16&descAlignY=62" width="100%" alt="flow~">
</div>

<table>
<tr>
<td width="42%" align="center" valign="middle">

<img src="logo.png" alt="flow~" width="96">

<br><br>

<a href="https://github.com/DemoLab/readme-typing-svg"><img src="https://readme-typing-svg.demolab.com?font=JetBrains+Mono&weight=700&size=15&duration=2600&pause=900&color=FFFFFF&background=000000&center=true&vCenter=true&width=330&height=36&lines=open.+play.+apply+HDR.;take+snacks.+enjoy.;dark.+quiet.+springy.;no+registry.+no+drama." alt="typing"></a>

</td>
<td width="58%" valign="middle">

![python](https://img.shields.io/badge/PYTHON-3.10+-000000?style=flat&labelColor=ffffff)
![qt](https://img.shields.io/badge/PYSIDE6-6.8+-ffffff?style=flat&labelColor=000000)
![portable](https://img.shields.io/badge/PORTABLE-NO_REGISTRY-000000?style=flat&labelColor=ffffff)

<br><br>

```text
╭─ FLOW INDEX ───────────────────────╮
│  [01] SYSTEM   ~►  #01-system      │
│  [02] KEYS     ~►  #02-keys        │
│  [03] BOOT     ~►  #03-boot        │
│  [04] FAQ      ~►  #04-faq         │
╰────────────────────────────────────╯
```

</td>
</tr>

<div align="center">

```mermaid
flowchart LR
    A(01 · Open) f1@--> B(02 · Play) f2@--> C(03 · Apply HDR) f3@--> D(04 · Take Snacks) f4@--> E(05 · Enjoy)
    f1@{ animate: true }
    f2@{ animate: true }
    f3@{ animate: true }
    f4@{ animate: true }
    classDef blk fill:#000000,stroke:#ffffff,stroke-width:2px,color:#ffffff
    classDef wht fill:#ffffff,stroke:#000000,stroke-width:2px,color:#000000
    class A,C,E blk
    class B,D wht
```

</div>

## 01. system

<table>
<tr>
<td width="50%" valign="top">

![flow](https://img.shields.io/badge/01-FLOW-000000?style=flat&labelColor=ffffff)

<br>

- **Library:** auto-sorts movies, series, extras, audio
- **Playback:** resume halfway · shuffle/repeat queue · `0.5x–2x`

</td>
<td width="50%" valign="top">

![formats](https://img.shields.io/badge/02-FORMATS-ffffff?style=flat&labelColor=000000)

<br>

- **Video (17):** `mp4 mkv avi mov webm flv m2ts wmv mpg vob` +
- **Audio (12):** `mp3 flac wav aac m4a ogg opus wma aiff mka` +
- **Stream:** `http` `https` `rtsp` `rtmp`

</td>
</tr>
<tr>
<td width="50%" valign="top">

![looks](https://img.shields.io/badge/03-PICTURE_%5BV%5D-ffffff?style=flat&labelColor=000000)

<br>

| look | bright | contrast | colour | warmth | vig |
|:--|:--:|:--:|:--:|:--:|:--:|
| `OFF` | `0` | `0` | `0` | `0` | `0` |
| `HDR` | `+0.04` | `+0.22` | `+0.20` | `0` | `0` |
| `CIN` | `-0.03` | `+0.16` | `-0.10` | `+0.35` | `0.45` |
| `VIB` | `+0.02` | `+0.10` | `+0.45` | `0` | `0` |

<sub>+ independent `2.39:1` bars switch</sub>

</td>
<td width="50%" valign="top">

![subs](https://img.shields.io/badge/04-SUBTITLES-000000?style=flat&labelColor=ffffff)

<br>

- **Auto:** `.srt .ass .ssa .vtt .sub` & `Subs/`
- **Embedded:** `MKV` · `MP4/MOV (mov_text)` · `ffmpeg`
- **No bitmap:** PGS / VobSub / DVB
- **Live:** drop file or **`Shift+C`** · **`Z/X`** ±0.1s

</td>
</tr>
</table>

## 02. keys

<table>
<tr>
<td width="33%" valign="top">

![play](https://img.shields.io/badge/PLAY-000000?style=flat)

| key | action |
|:--|:--|
| **`Space` `K`** | play / pause |
| **`<-` `->`** | skip (`Shift` big) |
| **`N` `P`** | next / prev |
| **`[` `]`** | speed |

</td>
<td width="33%" valign="top">

![av](https://img.shields.io/badge/AV-ffffff?style=flat&labelColor=ffffff&color=000000)

| key | action |
|:--|:--|
| **`Up` `Down`** | volume |
| **`M`** | mute |
| **`V`** | cycle look |
| **`F` `F11`** | fullscreen |

</td>
<td width="34%" valign="top">

![app](https://img.shields.io/badge/APP-000000?style=flat)

| key | action |
|:--|:--|
| **`C` / `Shift+C`** | subs / load |
| **`Z` `X`** | sync ±0.1s |
| **`Ctrl+O/B/L/,`** | open/lib/queue/set |
| **`Esc`** | back / close |

</td>
</tr>
</table>

## 03. boot

<table>
<tr>
<td width="52%" valign="top">

![install](https://img.shields.io/badge/INSTALL-WIN_%2F_LINUX-000000?style=flat&labelColor=ffffff)

<br>

**Windows** — Python 3.10+ (PATH) → `manage.bat` → **`I`**

```text
╭─ [I] install + shortcuts   [U] uninstall   [Q] quit ─╮
```

**Linux**

```bash
./manage.sh install && ./run.sh
```

</td>
<td width="48%" valign="middle">

```mermaid
flowchart TB
    UI(qml) a1@--> P(player.py)
    UI a2@--> L(library.py)
    P a3@--> Q(Qt)
    P a4@--> S(subs.py)
    P a5@--> D(dsp + vis)
    a1@{ animate: true }
    a2@{ animate: true }
    a3@{ animate: true }
    a4@{ animate: true }
    a5@{ animate: true }
    classDef blk fill:#000000,stroke:#ffffff,stroke-width:2px,color:#ffffff
    classDef wht fill:#ffffff,stroke:#000000,stroke-width:2px,color:#000000
    class UI,Q,S,D blk
    class P,L wht
```

<sub>data saved in `./data` · `numpy` optional</sub>

</td>
</tr>
</table>

## 04. faq

<table>
<tr>
<td width="50%" valign="top">

<details>
<summary><b>Picture button missing?</b></summary>
Only appears when a video is loaded.
</details>

<details>
<summary><b>Python not found?</b></summary>
Install Python 3.10+ and tick Add to PATH.
</details>

</td>
<td width="50%" valign="top">

<details>
<summary><b>Where do settings go?</b></summary>
Everything stays in <code>./data</code> on uninstall.
</details>

<details>
<summary><b>Subtitles not showing?</b></summary>
Image subs (PGS/VobSub) are unsupported; use <code>.srt</code>.
</details>

</td>
</tr>
</table>

<div align="center">
<img src="https://capsule-render.vercel.app/api?type=waving&height=95&color=000000&section=footer&reversal=true" width="100%" alt="">

<sub><code>made by xan</code></sub>
</div>