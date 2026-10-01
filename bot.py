
import os
import math
import sqlite3
import logging
import httpx
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
    PicklePersistence,
)
from scipy.spatial import cKDTree

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

WHEELMAP_TOKEN = os.environ.get("WHEELMAP_TOKEN", "")
MAX_RESULTS = 5
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plazas.db")

TEXTS = {
    "es": {
        "searching": "🔍 Buscando {mode} cercanos...",
        "not_found": "😞 No encontré {mode} en un radio de 2 km.\n\nPuede que no estén mapeados aún.",
        "found": "♿ *{n} {mode} encontrado(s) en {radio}*",
        "directions": "🧭 Cómo llegar a {name}",
        "more": "🔄 Ver más",
        "send_location": "📍 Envíame tu *ubicación* para buscar {mode}.\nPulsa el clip 📎 → Ubicación.",
        "new_parking": "📍 Envía la ubicación exacta de la nueva plaza y la añadiremos. (Usa /cancel para abortar)",
        "new_parking_added": "✅ Plaza enviada y pendiente de revisión. ¡Gracias por tu aportación!",
        "help": "♿ *DisZoneBot* - Radar de Accesibilidad\n\nComandos disponibles:\n/parking - ♿ Plazas de Aparcamiento PMR\n/newparking - 📍 Añadir nueva plaza PMR al mapa\n/food - 🍽️ Restaurantes y Bares\n/toilets - 🚻 Baños Públicos\n/shopping - 🛒 Supermercados y Tiendas\n/leisure - 🏛️ Ocio y Cultura",
        "cancelled": "🚫 Operación cancelada. Elige una categoría (ej: /parking) y envía tu ubicación."
    },
    "en": {
        "searching": "🔍 Searching for nearby {mode}...",
        "not_found": "😞 No {mode} found within 2 km.\n\nThey may not be mapped yet.",
        "found": "♿ *{n} {mode} found within {radio}*",
        "directions": "🧭 Directions to {name}",
        "more": "🔄 More results",
        "send_location": "📍 Send me your *location* to find {mode}.\nTap the clip 📎 → Location.",
        "new_parking": "📍 Send the exact location of the new parking spot and we'll add it. (Use /cancel to abort)",
        "new_parking_added": "✅ Parking spot submitted and pending review. Thank you for your contribution!",
        "help": "♿ *DisZoneBot* - Accessibility Radar\n\nCommands:\n/parking - ♿ Disabled Parking\n/newparking - 📍 Add a new PMR spot to the map\n/food - 🍽️ Restaurants & Bars\n/toilets - 🚻 Public Toilets\n/shopping - 🛒 Supermarkets & Shops\n/leisure - 🏛️ Leisure & Culture",
        "cancelled": "🚫 Operation cancelled. Choose a category (e.g. /parking) and send your location."
    },
}

CATEGORIES = {
    "parking": {"es": "Plazas de Aparcamiento PMR", "en": "Disabled Parking Spots"},
    "food": {"es": "Restaurantes y Bares accesibles", "en": "Accessible Restaurants & Bars", "wm_cats": ["restaurant", "fastfood", "coffee", "pub", "bar"]},
    "toilets": {"es": "Baños adaptados", "en": "Accessible Toilets", "wm_cats": ["toilets"]},
    "shopping": {"es": "Tiendas y Supermercados accesibles", "en": "Accessible Shopping", "wm_cats": ["supermarket", "convenience_store", "clothes", "department_store", "books"]},
    "leisure": {"es": "Cultura y Ocio accesible", "en": "Accessible Leisure & Culture", "wm_cats": ["museum", "cinema", "theater", "attraction", "park", "sports_center"]}
}

R_EARTH = 6371000

def latlon_to_cartesian(lat, lon):
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    return (
        R_EARTH * math.cos(lat_rad) * math.cos(lon_rad),
        R_EARTH * math.cos(lat_rad) * math.sin(lon_rad),
        R_EARTH * math.sin(lat_rad)
    )

class SpatialIndex:
    def __init__(self):
        self.tree = None
        self.plazas = []
        self.last_mtime = 0
        self.load_data()
        
    def load_data(self):
        if not os.path.exists(DB_PATH): return
        conn = sqlite3.connect(DB_PATH)
        try:
            rows = conn.execute("SELECT id, ciudad, lat, lon, fuente FROM plazas WHERE estado='verificada'").fetchall()
            self.plazas = []
            coords = []
            for r in rows:
                self.plazas.append(r)
                coords.append(latlon_to_cartesian(r[2], r[3]))
            if coords:
                self.tree = cKDTree(coords)
                logger.info(f"KDTree inicializado con {len(coords)} plazas.")
        except Exception as e:
            logger.error(f"Error DB: {e}")
        finally:
            conn.close()
            
    def check_reload(self):
        if not os.path.exists(DB_PATH): return
        current_mtime = os.path.getmtime(DB_PATH)
        if current_mtime > self.last_mtime:
            self.load_data()
            self.last_mtime = current_mtime
            
    def query(self, lat, lon, radius):
        self.check_reload()
        if not self.tree: return []
        cart = latlon_to_cartesian(lat, lon)
        theta = radius / R_EARTH
        chord = 2 * R_EARTH * math.sin(theta / 2)
        indices = self.tree.query_ball_point(cart, r=chord)
        
        results = []
        for idx in indices:
            pid, ciudad, plat, plon, fuente = self.plazas[idx]
            dist = haversine(lat, lon, plat, plon)
            if dist <= radius:
                results.append({
                    "id": pid,
                    "name": f"Plaza – {ciudad}",
                    "lat": plat,
                    "lon": plon,
                    "cat_emoji": "♿",
                    "info": fuente,
                    "_dist": dist,
                })
        results.sort(key=lambda x: x["_dist"])
        return results

spatial_index = SpatialIndex()

OSM_CACHE = {}

async def query_overpass(lat: float, lon: float, radius: int) -> list:
    cache_key = f"{round(lat, 3)}_{round(lon, 3)}_{radius}"
    now = time.time()
    if cache_key in OSM_CACHE and now - OSM_CACHE[cache_key]['time'] < 3600:
        return OSM_CACHE[cache_key]['data']

    query = f"""
    [out:json][timeout:10];
    (
      node["amenity"="parking_space"]["parking_space"="disabled"](around:{radius},{lat},{lon});
      node["amenity"="parking_space"]["access"="disabled"](around:{radius},{lat},{lon});
      way["amenity"="parking"]["capacity:disabled"](around:{radius},{lat},{lon});
    );
    out center body;
    """
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(OVERPASS_URL, data={"data": query}, timeout=15.0)
            if r.status_code != 200: return []
            
            results = []
            for e in r.json().get("elements", []):
                elat = e.get("center", {}).get("lat") or e.get("lat")
                elon = e.get("center", {}).get("lon") or e.get("lon")
                if elat and elon:
                    results.append({
                        "id": e.get("id"),
                        "name": "Plaza (OSM)",
                        "lat": elat,
                        "lon": elon,
                        "cat_emoji": "♿",
                        "info": "OpenStreetMap",
                        "_dist": haversine(lat, lon, elat, elon)
                    })
            OSM_CACHE[cache_key] = {'time': now, 'data': results}
            
            expired = [k for k, v in OSM_CACHE.items() if now - v['time'] > 3600]
            for k in expired: del OSM_CACHE[k]
            
            return results
    except Exception as e:
        logger.error(f"Error Overpass: {e}")
        return []

def haversine(lat1, lon1, lat2, lon2) -> float:
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def merge_parking(osm: list, local: list, max_res: int) -> list:
    osm_unique = []
    for o in osm:
        if not any(haversine(o["lat"], o["lon"], exist["lat"], exist["lon"]) < 10 for exist in osm_unique):
            osm_unique.append(o)
            
    combined = list(osm_unique)
    for loc in local:
        if not any(haversine(loc["lat"], loc["lon"], o["lat"], o["lon"]) < 15 for o in osm_unique):
            combined.append(loc)
            
    combined.sort(key=lambda x: x["_dist"])
    return combined[:max_res]

async def query_wheelmap(lat: float, lon: float, radius: int, categories: list) -> list:
    if not WHEELMAP_TOKEN:
        logger.warning("WHEELMAP_TOKEN no configurado en variables de entorno.")
        return []
    url = "https://accessibility.cloud/place-infos.json"
    params = {
        "appToken": WHEELMAP_TOKEN,
        "latitude": lat,
        "longitude": lon,
        "accuracy": radius,
        "includeCategories": ",".join(categories),
        "limit": 50
    }
    headers = {"Accept": "application/json"}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, params=params, headers=headers, timeout=10.0)
            if r.status_code != 200: return []
            
            results = []
            for f in r.json().get("features", []):
                props = f.get("properties", {})
                acc = props.get("accessibility", {}).get("accessibleWith", {}).get("wheelchair")
                if acc == False: continue # Ignorar sitios no accesibles
                
                name = props.get("name", "Desconocido")
                cat = props.get("category")
                plat, plon = f.get("geometry", {}).get("coordinates", [0,0])[1::-1] # [lon, lat] -> [lat, lon]
                
                status_emoji = "✅" if acc else ("⚠️" if acc is None else "❓")
                
                results.append({
                    "name": name,
                    "lat": plat,
                    "lon": plon,
                    "cat_emoji": "📌",
                    "info": f"{cat.capitalize()} | Silla de ruedas: {status_emoji}",
                    "_dist": haversine(lat, lon, plat, plon)
                })
            results.sort(key=lambda x: x["_dist"])
            return results
    except Exception as e:
        logger.error(f"Error Wheelmap: {e}")
        return []

def format_result(place: dict, idx: int, lang: str) -> str:
    name = place.get("name", f"Lugar #{idx}")
    dist = int(place["_dist"])
    emoji = place.get("cat_emoji", "📌")
    info = place.get("info", "")
    
    lineas = [f"{emoji} *{idx}. {name}*"]
    if info: lineas.append(f"ℹ️ {info}")
    lineas.append(TEXTS[lang]["distance"].format(dist=dist))
    return "\n".join(lineas)

async def set_search_mode(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str):
    context.user_data["mode"] = mode
    lang = context.user_data.get("lang", "es")
    mode_text = CATEGORIES[mode][lang]
    await update.message.reply_text(TEXTS[lang]["send_location"].format(mode=mode_text), parse_mode="Markdown")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_lang = update.effective_user.language_code
    if "lang" not in context.user_data:
        context.user_data["lang"] = "en" if user_lang and not user_lang.startswith("es") else "es"
    lang = context.user_data["lang"]
    
    await update.message.reply_text(TEXTS[lang]["help"], parse_mode="Markdown")

async def cmd_parking(update: Update, context: ContextTypes.DEFAULT_TYPE): await set_search_mode(update, context, "parking")
async def cmd_food(update: Update, context: ContextTypes.DEFAULT_TYPE): await set_search_mode(update, context, "food")
async def cmd_toilets(update: Update, context: ContextTypes.DEFAULT_TYPE): await set_search_mode(update, context, "toilets")
async def cmd_shopping(update: Update, context: ContextTypes.DEFAULT_TYPE): await set_search_mode(update, context, "shopping")
async def cmd_leisure(update: Update, context: ContextTypes.DEFAULT_TYPE): await set_search_mode(update, context, "leisure")


async def cmd_newparking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get("lang", "es")
    await update.message.reply_text(TEXTS[lang]["new_parking"], parse_mode="Markdown")
    context.user_data["esperando_nueva_plaza"] = True


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = os.environ.get("ADMIN_ID")
    if not admin_id or str(update.effective_user.id) != str(admin_id):
        return # Ignorar silenciosamente si no es admin

    try:
        conn = sqlite3.connect(DB_PATH)
        total_plazas = conn.execute("SELECT COUNT(*) FROM plazas WHERE estado='verificada'").fetchone()[0]
        pendientes = conn.execute("SELECT COUNT(*) FROM plazas WHERE estado='pendiente'").fetchone()[0]
        ciudades = conn.execute("SELECT COUNT(DISTINCT ciudad) FROM plazas").fetchone()[0]
        conn.close()

        stats_text = (
            "📊 *Panel de Administración - DisZoneBot*\n\n"
            f"♿ *Plazas Verificadas (KDTree):* {total_plazas}\n"
            f"⏳ *Aportaciones Pendientes:* {pendientes}\n"
            f"🏙️ *Ciudades o Fuentes distintas:* {ciudades}\n\n"
            f"🌲 *Estado KDTree:* Activo (Cargadas {len(spatial_index.plazas)} coordenadas)\n"
            "☁️ *Wheelmap API:* Configurada\n"
            "🌍 *Overpass API:* Fallback Activo"
        )
        await update.message.reply_text(stats_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error en stats: {e}")
        await update.message.reply_text("❌ Error al obtener estadísticas.")

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get("lang", "es")
    if context.user_data.get("esperando_nueva_plaza"):
        context.user_data["esperando_nueva_plaza"] = False
        await update.message.reply_text(TEXTS[lang]["cancelled"])
    else:
        await update.message.reply_text("👍", parse_mode="Markdown")

async def admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split("_")
    action = parts[1]
    plaza_id = parts[2]
    
    conn = sqlite3.connect(DB_PATH)
    if action == "approve":
        conn.execute("UPDATE plazas SET estado='verificada' WHERE id=?", (plaza_id,))
        text = f"✅ Plaza {plaza_id} aprobada y añadida al mapa mundial del bot."
    else:
        conn.execute("UPDATE plazas SET estado='rechazada' WHERE id=?", (plaza_id,))
        text = f"❌ Plaza {plaza_id} rechazada."
    conn.commit()
    conn.close()
    
    spatial_index.check_reload()
    
    await query.edit_message_text(text=query.message.text + f"\n\nEstado actual: {text}")

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lat = update.message.location.latitude
    lon = update.message.location.longitude
    
    if context.user_data.get("esperando_nueva_plaza"):
        context.user_data["esperando_nueva_plaza"] = False
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.execute(
                "INSERT INTO plazas (ciudad, lat, lon, fuente, estado) VALUES (?, ?, ?, ?, ?)",
                ("Comunidad", lat, lon, "Aportación de Usuario", "pendiente"),
            )
            plaza_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            await update.message.reply_text(TEXTS[lang]["new_parking_added"])
            
            admin_id = os.environ.get("ADMIN_ID")
            if admin_id:
                keyboard = [
                    [
                        InlineKeyboardButton("✅ Aprobar", callback_data=f"admin_approve_{plaza_id}"),
                        InlineKeyboardButton("❌ Rechazar", callback_data=f"admin_reject_{plaza_id}")
                    ]
                ]
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"Nueva plaza reportada por la comunidad:\nLat: {lat}\nLon: {lon}\nhttps://www.google.com/maps?q={lat},{lon}",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        except Exception as e:
            logger.error(f"Error guardando plaza: {e}")
            await update.message.reply_text("Error interno al guardar la plaza.")
        return

    mode = context.user_data.get("mode", "parking")

    lang = context.user_data.get("lang", "es")
    
    mode_text = CATEGORIES[mode][lang]
    msg = await update.message.reply_text(TEXTS[lang]["searching"].format(mode=mode_text))
    
    # Búsqueda
    results = []
    if mode == "parking":
        for r in (500, 2000):
            local_results = spatial_index.query(lat, lon, r)
            osm_results = await query_overpass(lat, lon, r)
            results = merge_parking(osm_results, local_results, 50)
            if results: break
    else:
        for r in (1000, 3000):
            results = await query_wheelmap(lat, lon, r, CATEGORIES[mode]["wm_cats"])
            if results: break
            
    if not results:
        await msg.edit_text(TEXTS[lang]["not_found"].format(mode=mode_text), parse_mode="Markdown")
        return
        
    context.user_data["results"] = results
    context.user_data["res_idx"] = 0

    top_results = results[:MAX_RESULTS]
    texto = TEXTS[lang]["found"].format(n=len(results), mode=mode_text, radio=f"{int(results[-1]['_dist'])}m") + "\n\n"
    texto += "\n\n".join(format_result(p, i + 1, lang) for i, p in enumerate(top_results))

    keyboard = []
    for i, p in enumerate(top_results, 1):
        keyboard.append([InlineKeyboardButton(TEXTS[lang]["directions"].format(name=p["name"]), url=f"https://www.google.com/maps/dir/?api=1&destination={p['lat']},{p['lon']}&travelmode=driving")])

    if len(results) > MAX_RESULTS:
        keyboard.append([InlineKeyboardButton(TEXTS[lang]["more"], callback_data="more_results")])

    await msg.edit_text(texto, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def more_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = context.user_data.get("lang", "es")
    results = context.user_data.get("results", [])
    idx = context.user_data.get("res_idx", 0) + MAX_RESULTS
    context.user_data["res_idx"] = idx
    top_results = results[idx : idx + MAX_RESULTS]

    if not top_results:
        await query.answer("No hay más resultados.", show_alert=True)
        return

    mode = context.user_data.get("mode", "parking")
    mode_text = CATEGORIES[mode][lang]
    
    texto = TEXTS[lang]["found"].format(n=len(results), mode=mode_text, radio="extendido") + "\n\n"
    texto += "\n\n".join(format_result(p, idx + i + 1, lang) for i, p in enumerate(top_results))

    keyboard = []
    for i, p in enumerate(top_results, 1):
        keyboard.append([InlineKeyboardButton(TEXTS[lang]["directions"].format(name=p["name"]), url=f"https://www.google.com/maps/dir/?api=1&destination={p['lat']},{p['lon']}&travelmode=driving")])

    if idx + MAX_RESULTS < len(results):
        keyboard.append([InlineKeyboardButton(TEXTS[lang]["more"], callback_data="more_results")])

    await query.edit_message_text(texto, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get("lang", "es")
    await update.message.reply_text(TEXTS[lang]["help"], parse_mode="Markdown")

def main():
    token = os.environ.get("TELEGRAM_TOKEN")
    persistence = PicklePersistence(filepath="bot_data")
    app = Application.builder().token(token).persistence(persistence).build()
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("parking", cmd_parking))
    app.add_handler(CommandHandler("food", cmd_food))
    app.add_handler(CommandHandler("toilets", cmd_toilets))
    app.add_handler(CommandHandler("shopping", cmd_shopping))
    app.add_handler(CommandHandler("newparking", cmd_newparking))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CallbackQueryHandler(admin_action, pattern="^admin_"))
    app.add_handler(CommandHandler("leisure", cmd_leisure))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_handler(CallbackQueryHandler(more_results, pattern="^more_results$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    if token != "dummy":
        logger.info("Bot iniciado...")
        app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()







