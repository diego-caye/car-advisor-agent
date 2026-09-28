# KB claims worth double-checking

`00-master-build.md` §12 asks that, when closing F5, we list the claims the human should verify before delivery. The KB is generic educational content, with no brands or prices, but several claims are quantitative or depend on the Peruvian context and deserve a second look.

**None of these claims block the demo.** If any turns out to be questionable, fix the markdown and re-ingest (`uv run python scripts/ingest_kb.py`): the hash detects the change and only re-embeds that chunk.

## Specific figures

| File | Claim | Why it's worth checking |
|---|---|---|
| `motorizacion-gasolina-diesel.md` | "A diesel consumes roughly 20 to 30% less than a gasoline engine of equivalent power" | The range is reasonable as a general rule, but varies a lot with engine type and usage cycle |
| `motorizacion-hibridos.md` | MHEV saves "between 5 and 12%" | Depends on the system; some manufacturers state different figures |
| `motorizacion-hibridos.md` | HEV reduces consumption "25 to 40% in the city" | A plausible range but optimistic in very light traffic |
| `motorizacion-electricos.md` | "Expect 70 to 80% of the rated range" | A practical rule of thumb; depends heavily on speed and weather |
| `consumo-y-habitos.md` | "Going from 100 to 120 km/h can raise consumption by 20% or more" | Correct in order of magnitude; the exact figure depends on the vehicle |
| `consumo-y-habitos.md` | "15 to 30% more consumption than the rated figure" | Depends on the current homologation protocol |
| `mantenimiento-basico.md` | Brake fluid "typically every two years" | It's the usual interval, but the manufacturer's manual has the final word |
| `mantenimiento-basico.md` | Minimum legal tread depth "1.6 mm" | **Verify against current Peruvian regulations**; it's the common value in several jurisdictions |
| `segmentos-catalogo.md` | The whole table of lengths, seats, and engine displacement | These are typical ranges made up as a reference; worth cross-checking against two or three real models per segment |

## Claims about the Peruvian context

| File | Claim | Why it's worth checking |
|---|---|---|
| `motorizacion-glp-gnv.md` | "A well-developed network of fueling stations in Lima and Callao" with less availability elsewhere | Generally true; worth confirming it's still the case |
| `motorizacion-glp-gnv.md` | "Mandatory periodic inspection and recertification" of tanks | The requirement exists; the exact interval is deliberately not stated |
| `motorizacion-electricos.md` | "The public network is concentrated in a few areas" | May have changed; verify before recording the video |
| `auto-segun-uso.md` | "Power loss becomes significant above 3,000 meters" | Correct order of magnitude; the exact threshold is gradual, not a hard cutoff |

## General technical claims

These are the most solid, but listed here for transparency:

- A diesel's particulate filter needs sustained highway trips to regenerate, and exclusively urban use clogs it (`motorizacion-gasolina-diesel.md`).
- ESC is one of the systems that has done the most to reduce crash severity after the seatbelt (`seguridad-y-adas.md`). The claim is widely supported, but no specific source is cited in the text.
- Fast charging is measured from 10% to 80% because past that point it slows down to protect the battery (`motorizacion-electricos.md`).
- A 4x4 doesn't help you brake (`transmision-y-traccion.md`).

## Deliberate content decisions

- **No brands or models.** No claim names a manufacturer. The `test_la_kb_real_no_menciona_precios_ni_marcas` test automatically verifies that no price symbols appear.
- **No prices or financing terms**, in line with the agent's policy (spec 05).
- **No maintenance intervals in specific kilometers**, except where it's clarified that the manufacturer's manual has the final word. Giving exact figures would mean inventing specifications.
