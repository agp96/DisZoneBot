# ♿ DisZoneBot

**DisZoneBot** is a powerful Telegram bot that serves as a global accessibility radar. It helps users find nearby disabled parking spaces (PMR) and accessible points of interest (restaurants, toilets, shops, leisure, etc.) in real time.

Try it on Telegram: **[@DisZoneBot](https://t.me/DisZoneBot)**

---

## 🚀 Features
- **Disabled Parking Finder**: Instantly locates PMR parking spaces using a local spatial cache (KD-Tree) with automatic real-time global fallback via **OpenStreetMap (Overpass API)**.
- **Accessibility Radar**: Finds nearby wheelchair-accessible places (restaurants, cafes, toilets, supermarkets, culture & leisure) powered by the **Wheelmap / Accessibility Cloud API**.
- **Community Driven**: Users can submit unmapped parking spots directly via `/newparking` for administrator approval.
- **Bilingual Support**: Automatically detects and responds in Spanish or English based on the user's Telegram client settings.

---

## 🛠️ Commands
- `/parking` — ♿ Search for Disabled Parking spots (PMR)
- `/food` — 🍽️ Search for accessible Restaurants & Bars
- `/toilets` — 🚻 Search for accessible Public Toilets
- `/shopping` — 🛒 Search for accessible Supermarkets & Shops
- `/leisure` — 🏛️ Search for accessible Leisure & Culture
- `/newparking` — 📍 Submit a new PMR spot to the community map
- `/cancel` — 🚫 Cancel current operation
- `/help` — Show usage instructions

---

## 📊 Data Sources & Architecture
1. **[OpenStreetMap](https://www.openstreetmap.org/) (Overpass API)**: Dynamic global data for PMR parking spaces worldwide.
2. **[Wheelmap / Accessibility Cloud](https://accessibility.cloud/)**: Global dataset for accessible points of interest across multiple categories.
3. **Local Spatial Cache / Database (SQLite + KD-Tree)**: Fast nearest-neighbor spatial queries when local datasets or community submissions are present.

> **Note on Data**: Large municipal raw datasets (`Aparcamientos Ciudades/`) and local SQLite databases (`plazas.db`) are ignored by Git (`.gitignore`). The bot works globally out-of-the-box leveraging OpenStreetMap and Wheelmap APIs.

---

## ⚙️ Deployment (Docker / Cloud)

1. **Clone the repository**:
   ```bash
   git clone https://github.com/your-username/DisZoneBot.git
   cd DisZoneBot
   ```

2. **Configure environment variables** in a `.env` file:
   ```env
   TELEGRAM_TOKEN=your_telegram_bot_token
   ADMIN_ID=your_telegram_numeric_id
   WHEELMAP_TOKEN=your_accessibility_cloud_read_token
   ```

3. **Deploy with Docker Compose**:
   ```bash
   docker-compose up -d --build
   ```

---

## 📝 License
Code: MIT License · Data: ODbL (OpenStreetMap)
