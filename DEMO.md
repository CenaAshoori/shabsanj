# Five-minute demo: ShabSanj

**Goal:** show how a traveller can compare hotel providers for the same stay, and where the current public-data prototype stops. Keep the recording under five minutes.

| Time | On screen | Say |
| --- | --- | --- |
| 0:00–0:30 | Home/search | “Torob makes one product comparable across shops. Hotels have the same problem, with a harder identity and rate match: one property can appear on several booking sites, and the cheapest headline price may describe a different room or set of terms.” |
| 0:30–1:15 | Search `هتل کنار دریا تا ۸ میلیون` | Show the interpreted destination and budget, then choose Kish or a Caspian city. Coast classification applies to the destination city. |
| 1:15–2:15 | Open a hotel with multiple provider observations | Point to normalized property name, location, provider links, observed prices and capture times. Explain that Tournegar may show a stay package while the other sites show starting one-night prices. |
| 2:15–3:10 | Open **تورهای این هتل**, then switch to **تورها** | Show the packages connected to the property and the schematic route map. Follow the booking link and open **آمار کلیک‌ها** to see the outbound click count. |
| 3:10–4:10 | Brief code/data view or refresh flow | Explain how OpenRouter function calling produces validated local search filters and how the crawler keeps the price basis, provider link, and observation time with each offer. Show only features that work in the recording. |
| 4:10–4:50 | Return to result page | “A production product would use provider APIs or agreements for live inventory and exact checkout totals. This prototype demonstrates the search, grouping, ranking and honest handoff first.” |
| 4:50–5:00 | Closing view | “This is Torob for hotel decisions: one place to compare providers while keeping the source and terms visible.” |

## Recording checklist

1. Start the app with `./run.sh` and open `http://127.0.0.1:8765` before recording.
2. Try `هتل اسپیناس بلوار تهران` to compare providers for one hotel. If a refresh changes the results, show the actual result and explain any missing provider.
3. Keep dates, room terms and availability labelled as indicative unless a provider confirms them live.
4. Record a real interaction and a short explanation of one technical tradeoff. Show the final UI, not a slide-only pitch.
5. Keep the video at **five minutes or less**; the challenge page also allows a video link instead of an uploaded file.
