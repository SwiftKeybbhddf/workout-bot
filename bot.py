import logging
import json
import os
import signal
import sys
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater, 
    CommandHandler, 
    MessageHandler, 
    Filters, 
    CallbackContext, 
    ConversationHandler,
    CallbackQueryHandler
)

# ========== НАСТРОЙКА ЛОГГИРОВАНИЯ ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Глобальная переменная для graceful shutdown
updater = None

def signal_handler(signum, frame):
    """Обработчик сигналов для graceful shutdown"""
    print(f"📞 Получен сигнал {signum}, завершаем работу бота...")
    
    global updater
    if updater is not None:
        print("🛑 Останавливаем updater...")
        updater.stop()
        print("✅ Updater остановлен")
    
    print("👋 Бот завершил работу")
    sys.exit(0)

# Регистрируем обработчики сигналов
signal.signal(signal.SIGTERM, signal_handler)  # Для Railway
signal.signal(signal.SIGINT, signal_handler)   # Для локального Ctrl+C

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.environ.get('BOT_TOKEN')

if not BOT_TOKEN:
    print("❌ ОШИБКА: BOT_TOKEN не найден!")
    exit(1)

print("✅ BOT_TOKEN найден, запускаем бота...")

TRAINING_PROGRAMS = {
    "День А": {
        "description": "🏋️ Акцент на горизонтальные жимы и вертикальные тяги",
        "exercises": [
            "Жим ногами в платформе (4x8-12)",
            "Подтягивания широким хватом (3xдо отказа)",
            "Жим штанги лежа на горизонтальной скамье (4x6-10)", 
            "Жим гантелей сидя (3x8-12)",
            "Подъем штанги на бицепс (3x10-12)",
            "Разгибание рук на блоке (канат) (3x12-15)",
            "Подъем ног в висе (3x12-15)"
        ]
    },
    "День Б": {
        "description": "💪 Акцент на вертикальные жимы и горизонтальные тяги", 
        "exercises": [
            "Румынская тяга со штангой (4x10-12)",
            "Тяга штанги в наклоне (4x8-12)",
            "Жим гантелей на наклонной скамье (30°) (4x10-12)",
            "Тяга штанги к подбородку широким хватом (3x10-15)",
            "Подъем гантелей на бицепс сидя (3x10-12)",
            "Французский жим лежа (EZ-гриф) (3x10-12)",
            "Скручивания на римском стуле (3x15-20)"
        ]
    }
}

# Состояния разговора
CHOOSING_DAY, CHOOSING_EXERCISE, ENTERING_EXERCISE_DATA, WEIGHING = range(4)
DATA_FILE = 'user_data.json'

# ========== ФУНКЦИИ РАБОТЫ С ДАННЫМИ ==========
def load_user_data():
    """Загрузка данных пользователей из файла"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"Ошибка загрузки данных: {e}")
    return {}

def save_user_data(data):
    """Сохранение данных пользователей в файл"""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения данных: {e}")

def get_weight_history(user_id):
    """Получает историю взвешиваний пользователя"""
    user_data = load_user_data()
    if user_id not in user_data:
        return []
    return user_data[user_id].get('weight_history', [])

def save_weight(user_id, weight):
    """Сохраняет вес пользователя"""
    user_data = load_user_data()
    if user_id not in user_data:
        user_data[user_id] = {'username': '', 'history': [], 'weight_history': []}
    
    weight_record = {
        'weight': weight,
        'date': datetime.now().isoformat(),
        'timestamp': datetime.now().strftime('%d.%m.%Y %H:%M')
    }
    
    user_data[user_id]['weight_history'].append(weight_record)
    save_user_data(user_data)
    return weight_record

def format_weight_history(weight_history):
    """Форматирует историю взвешиваний для отображения"""
    if not weight_history:
        return "📊 История взвешиваний пуста"
    
    lines = []
    for i, record in enumerate(weight_history[-5:], 1):  # Последние 5 записей
        lines.append(f"{i}. {record['timestamp']}: {record['weight']}кг")
    
    return "📊 История взвешиваний:\n" + "\n".join(lines)

def get_weight_progress(weight_history):
    """Анализирует прогресс веса"""
    if len(weight_history) < 2:
        return "💡 Продолжайте взвешиваться для отслеживания прогресса"
    
    current = weight_history[-1]['weight']
    previous = weight_history[-2]['weight']
    difference = current - previous
    
    if difference > 0:
        return f"📈 Набор массы: +{difference:.1f}кг"
    elif difference < 0:
        return f"📉 Снижение веса: {difference:.1f}кг"
    else:
        return "⚖️ Вес стабилен"

# ========== ФУНКЦИИ ТАЙМЕРА ==========
def timer_callback(context: CallbackContext):
    """Колбэк для завершения таймера"""
    job = context.job
    chat_id = job.context['chat_id']
    timer_name = job.context['timer_name']
    
    try:
        # Отправляем уведомление о завершении таймера
        context.bot.send_message(
            chat_id=chat_id,
            text=f"🎯 {timer_name} завершен! Можно делать следующий подход! 💪"
        )
        print(f"✅ Уведомление о завершении таймера отправлено в чат {chat_id}")
    except Exception as e:
        print(f"❌ Ошибка отправки уведомления таймера: {e}")
        logger.error(f"Ошибка отправки уведомления таймера: {e}")

def start_timer_progress(context: CallbackContext):
    """Функция для обновления прогресса таймера"""
    job = context.job
    chat_id = job.context['chat_id']
    timer_name = job.context['timer_name']
    remaining = job.context['remaining']
    message_id = job.context.get('message_id')
    
    if remaining <= 0:
        # Таймер завершен - эта функция больше не вызывается
        return
    
    try:
        if message_id:
            # Обновляем существующее сообщение
            context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"⏰ Таймер {timer_name}\nОсталось: {remaining} сек."
            )
        else:
            # Создаем новое сообщение
            message = context.bot.send_message(
                chat_id=chat_id,
                text=f"⏰ Таймер {timer_name}\nОсталось: {remaining} сек."
            )
            job.context['message_id'] = message.message_id
        
        # Уменьшаем оставшееся время
        job.context['remaining'] = remaining - 1
        
    except Exception as e:
        print(f"❌ Ошибка обновления таймера: {e}")
        logger.error(f"Ошибка обновления таймера: {e}")

def set_timer(update: Update, context: CallbackContext, duration: int, timer_name: str):
    """Устанавливает таймер через job queue"""
    chat_id = update.effective_message.chat_id
    
    # Создаем контекст для основного таймера (завершение)
    timer_job_context = {
        'chat_id': chat_id,
        'timer_name': timer_name
    }
    
    # Создаем контекст для прогресса таймера
    progress_job_context = {
        'chat_id': chat_id,
        'timer_name': timer_name,
        'remaining': duration
    }
    
    # Запускаем прогресс таймера с интервалом 1 секунда
    progress_job = context.job_queue.run_repeating(
        start_timer_progress,
        interval=1,
        first=0,
        context=progress_job_context,
        name=f"timer_progress_{chat_id}"
    )
    
    # Запускаем основной таймер для завершения
    context.job_queue.run_once(
        timer_callback,
        duration,
        context=timer_job_context,
        name=f"timer_end_{chat_id}"
    )
    
    # Также останавливаем прогресс таймера после завершения
    context.job_queue.run_once(
        lambda ctx: progress_job.schedule_removal(),
        duration,
        context={},
        name=f"timer_cleanup_{chat_id}"
    )
    
    print(f"✅ Таймер {timer_name} установлен на {duration} секунд для чата {chat_id}")
    return f"⏰ Таймер {timer_name} установлен на {duration} секунд"

# ========== ФУНКЦИИ АНАЛИТИКИ И РЕКОМЕНДАЦИЙ ==========
def get_exercise_history(user_id, exercise_name, limit=3):
    """Получает историю выполнения конкретного упражнения"""
    user_data = load_user_data()
    
    if user_id not in user_data or not user_data[user_id].get('history'):
        return []
    
    history = user_data[user_id]['history']
    exercise_history = []
    
    # Проходим по всем тренировкам в обратном порядке (от новых к старым)
    for session in reversed(history):
        for exercise in session.get('exercises', []):
            if exercise['name'] == exercise_name:
                session_date = datetime.fromisoformat(session['start_time']).strftime('%d.%m.%Y')
                exercise_history.append({
                    'date': session_date,
                    'weight': exercise['weight'],
                    'reps': exercise['reps'],
                    'day': session['day']
                })
                # Останавливаемся когда набрали нужное количество записей
                if limit and len(exercise_history) >= limit:
                    return exercise_history
    
    return exercise_history

def get_full_exercise_history(user_id, exercise_name):
    """Получает полную историю упражнения для аналитики"""
    return get_exercise_history(user_id, exercise_name, limit=None)

def format_exercise_history(history):
    """Форматирует историю упражнения для отображения"""
    if not history:
        return "📝 Ранее не выполнялось"
    
    lines = []
    for i, record in enumerate(history, 1):
        lines.append(f"{i}. {record['date']} ({record['day']}): {record['weight']}кг × {record['reps']}повт.")
    
    return "\n".join(lines)

def create_simple_ascii_chart(history):
    """Создает простой ASCII-график прогресса"""
    if not history or len(history) < 2:
        return "Недостаточно данных для графика"
    
    # Берем последние 8 записей
    recent_history = history[:8]
    weights = [h['weight'] for h in recent_history]
    
    min_weight = min(weights)
    max_weight = max(weights)
    
    if min_weight == max_weight:
        return "📊 Вес стабилен: {}кг".format(weights[0])
    
    chart_lines = []
    for weight in reversed(weights):
        # Нормализуем вес для отображения в 20 символах
        normalized = int((weight - min_weight) / (max_weight - min_weight) * 15)
        bar = "█" * (normalized + 1)
        chart_lines.append(f"{weight:4}кг |{bar}")
    
    return "📊 График прогресса:\n" + "\n".join(chart_lines)

def generate_smart_recommendations(user_id, exercise_name):
    """Генерирует умные рекомендации на основе истории тренировок"""
    history = get_full_exercise_history(user_id, exercise_name)
    if not history or len(history) < 3:
        return "💡 Продолжайте собирать данные для персонализированных рекомендаций"
    
    current = history[0]
    previous = history[1] if len(history) > 1 else None
    two_back = history[2] if len(history) > 2 else None
    
    recommendations = []
    
    # Анализ прогресса веса
    if previous and two_back:
        weight_trend = current['weight'] - two_back['weight']
        reps_trend = current['reps'] - two_back['reps']
        
        # Рекомендации по весу
        if weight_trend == 0 and current['reps'] >= 10:
            recommendations.append("🎯 Пора увеличить вес на 2.5-5 кг")
        elif weight_trend > 0:
            recommendations.append(f"🚀 Отличный прогресс! +{weight_trend}кг за 2 тренировки")
        elif weight_trend < 0:
            recommendations.append("💪 Вернитесь к предыдущему весу и поработайте над техникой")
        
        # Рекомендации по повторениям
        if reps_trend >= 3:
            recommendations.append("🔥 Отличная выносливость! Можно добавить вес")
        elif reps_trend <= -3:
            recommendations.append("📉 Упали повторения? Проверьте восстановление и питание")
    
    # Анализ стабильности
    recent_weights = [h['weight'] for h in history[:3]]
    if len(set(recent_weights)) == 1:  # Все веса одинаковые
        avg_reps = sum([h['reps'] for h in history[:3]]) / 3
        if avg_reps >= 12:
            recommendations.append("⚡ Вы стабильно делаете 12+ повторений - пора увеличивать вес!")
        elif avg_reps <= 8:
            recommendations.append("📊 Мало повторений? Попробуйте снизить вес на 5-10%")
    
    # Анализ частоты тренировок
    if len(history) >= 4:
        dates = [datetime.strptime(h['date'], '%d.%m.%Y') for h in history[:4]]
        date_diffs = [(dates[i] - dates[i+1]).days for i in range(len(dates)-1)]
        avg_frequency = sum(date_diffs) / len(date_diffs)
        
        if avg_frequency > 7:
            recommendations.append("📅 Тренируйтесь чаще (2-3 раза в неделю) для лучшего прогресса")
        elif avg_frequency < 2:
            recommendations.append("🛌 Давайте мышцам больше времени на восстановление (2-3 дня между тренировками)")
    
    if not recommendations:
        recommendations.append("💪 Продолжайте в том же духе! Ваш прогресс стабилен")
    
    return "\n".join(recommendations)

def check_workout_reminders(user_id):
    """Проверяет необходимость напоминаний"""
    user_data = load_user_data()
    
    if user_id not in user_data or not user_data[user_id].get('history'):
        return "💡 Начните первую тренировку! Используйте /train"
    
    history = user_data[user_id]['history']
    if not history:
        return "💡 Начните первую тренировку! Используйте /train"
    
    last_workout = history[-1]
    last_date = datetime.fromisoformat(last_workout['start_time'])
    days_since_last = (datetime.now() - last_date).days
    
    reminders = []
    
    if days_since_last >= 3:
        reminders.append(f"🕐 Прошло {days_since_last} дней с последней тренировки")
    
    if days_since_last >= 7:
        reminders.append("⚠️ Длительный перерыв может замедлить прогресс")
    
    # Анализ прогресса
    progress_data = {}
    for session in history[-3:]:
        for exercise in session.get('exercises', []):
            name = exercise['name']
            if name not in progress_data:
                progress_data[name] = []
            progress_data[name].append(exercise)
    
    for exercise_name, exercises in progress_data.items():
        if len(exercises) >= 2:
            last = exercises[0]
            prev = exercises[1]
            if last['weight'] == prev['weight'] and last['reps'] >= 10:
                reminders.append(f"🎯 {exercise_name}: готовы к увеличению веса!")
    
    if reminders:
        return "💡 Напоминания:\n" + "\n".join(reminders)
    
    return None

def get_detailed_exercise_stats(user_id, exercise_name):
    """Возвращает детальную статистику по упражнению"""
    history = get_full_exercise_history(user_id, exercise_name)
    if not history:
        return None
    
    weights = [h['weight'] for h in history]
    reps = [h['reps'] for h in history]
    
    stats = {
        'total_workouts': len(history),
        'current_weight': weights[0],
        'current_reps': reps[0],
        'best_weight': max(weights),
        'best_reps': max(reps),
        'avg_weight': sum(weights) / len(weights),
        'avg_reps': sum(reps) / len(reps),
        'weight_progress': weights[0] - weights[-1],
        'reps_progress': reps[0] - reps[-1],
        'consistency': len(set(weights)) / len(weights)  # 1 = полностью стабильно
    }
    
    return stats

def format_detailed_stats(stats, exercise_name):
    """Форматирует детальную статистику для отображения"""
    if not stats:
        return f"📊 Нет данных по упражнению: {exercise_name}"
    
    return f"""
📈 <b>Детальная статистика: {exercise_name}</b>

📅 Всего тренировок: <b>{stats['total_workouts']}</b>
⚖️ Текущий вес: <b>{stats['current_weight']}кг × {stats['current_reps']}повт.</b>

🏆 Рекорды:
• Макс. вес: <b>{stats['best_weight']}кг</b>
• Макс. повторения: <b>{stats['best_reps']}повт.</b>

📊 Средние показатели:
• Вес: <b>{stats['avg_weight']:.1f}кг</b>
• Повторения: <b>{stats['avg_reps']:.1f}повт.</b>

📈 Прогресс с начала:
• Вес: <b>{stats['weight_progress']:+.1f}кг</b>
• Повторения: <b>{stats['reps_progress']:+.1f}повт.</b>

🎯 Стабильность: <b>{stats['consistency']*100:.0f}%</b>
"""

def get_progress_comparison(current_weight, current_reps, previous_history):
    """Сравнивает текущий результат с предыдущими"""
    if not previous_history:
        return "🎉 Первая запись этого упражнения!"
    
    last_record = previous_history[0]
    last_weight = last_record['weight']
    last_reps = last_record['reps']
    
    if current_weight > last_weight:
        return f"🚀 Прогресс! +{current_weight - last_weight}кг к весу"
    elif current_reps > last_reps:
        return f"💪 Прогресс! +{current_reps - last_reps} повторений"
    elif current_weight == last_weight and current_reps == last_reps:
        return "⚖️ Такой же результат как в прошлый раз"
    else:
        return "📉 Немного ниже прошлого результата. В следующий раз получится лучше!"

# ========== ФУНКЦИИ ИНТЕРФЕЙСА ==========
def get_exercise_keyboard(day, completed_exercises, user_id=None):
    """Создает расширенную клавиатуру для выбора упражнений"""
    exercises = TRAINING_PROGRAMS[day]['exercises']
    keyboard = []
    
    for i, exercise in enumerate(exercises):
        status = "✅" if i in completed_exercises else "◻️"
        
        # Добавляем подсказку с последним результатом
        hint = ""
        if user_id:
            history = get_exercise_history(user_id, exercise, limit=1)
            if history:
                last_record = history[0]
                hint = f" ({last_record['weight']}кг×{last_record['reps']})"
        
        keyboard.append([InlineKeyboardButton(
            f"{status} {i+1}. {exercise.split(' (')[0]}{hint}", 
            callback_data=f"ex_{i}"
        )])
    
    # Добавляем расширенные кнопки управления
    keyboard.append([
        InlineKeyboardButton("📊 Прогресс", callback_data="progress"),
        InlineKeyboardButton("🎯 Рекомендации", callback_data="reminders")
    ])
    keyboard.append([
        InlineKeyboardButton("📈 Статистика", callback_data="stats"),
        InlineKeyboardButton("🏁 Завершить", callback_data="finish")
    ])
    
    return InlineKeyboardMarkup(keyboard)

def get_exercise_detail_keyboard():
    """Создает клавиатуру для окна упражнения с таймерами"""
    keyboard = [
        [
            InlineKeyboardButton("⏱ 1.5 мин", callback_data="timer_90"),
            InlineKeyboardButton("⏱ 3 мин", callback_data="timer_180")
        ],
        [
            InlineKeyboardButton("⏱ 2 мин", callback_data="timer_120"),
            InlineKeyboardButton("⏱ 5 мин", callback_data="timer_300")
        ],
        [
            InlineKeyboardButton("📊 Прогресс тренировки", callback_data="progress"),
            InlineKeyboardButton("🎯 Рекомендации", callback_data="reminders")
        ],
        [
            InlineKeyboardButton("🔙 К списку упражнений", callback_data="back_to_exercises"),
            InlineKeyboardButton("🏁 Завершить", callback_data="finish")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# ========== ОСНОВНЫЕ ФУНКЦИИ БОТА ==========
def start(update: Update, context: CallbackContext):
    """Команда /start - начало работы"""
    user = update.effective_user
    welcome_text = f"""
🤖 Привет, {user.first_name}!

🏋️‍♂️ Добро пожаловать в трекер тренировок!

<b>Новые возможности:</b>
• ⏱ <b>Таймеры отдыха</b> - 1.5, 3 минуты и другие
• ⚖️ <b>Трекер веса</b> - отслеживание прогресса массы тела
• 📊 <b>Графики прогресса</b> - визуализация ваших результатов
• 🎯 <b>Умные рекомендации</b> - персонализированные советы

<b>Основные команды:</b>
/train - Начать новую тренировку
/progress - Посмотреть историю тренировок
/stats - Статистика прогресса
/weight - Записать текущий вес
/help - Помощь по использованию
    """
    update.message.reply_text(welcome_text, parse_mode='HTML')

def start_training_command(update: Update, context: CallbackContext):
    """Команда /train - начало тренировки"""
    return choose_training_day(update, context)

def choose_training_day(update: Update, context: CallbackContext):
    """Выбор дня тренировки"""
    keyboard = [["День А", "День Б"], ["/cancel"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    
    programs_info = "📋 <b>Программы тренировок:</b>\n\n"
    for day, program in TRAINING_PROGRAMS.items():
        programs_info += f"<b>{day}</b>\n{program['description']}\n<i>Упражнений: {len(program['exercises'])}</i>\n\n"
    
    programs_info += "Выберите день тренировки:"
    update.message.reply_text(programs_info, parse_mode='HTML', reply_markup=reply_markup)
    return CHOOSING_DAY

def show_exercise_list(update: Update, context: CallbackContext):
    """Показывает список упражнений для выбранного дня"""
    if update.message:
        day = update.message.text
    else:
        day = context.user_data.get('current_day')
    
    user_id = str(update.effective_user.id)
    
    if day not in TRAINING_PROGRAMS:
        update.message.reply_text("❌ Пожалуйста, выберите день из предложенных вариантов", reply_markup=ReplyKeyboardRemove())
        return choose_training_day(update, context)
    
    user_data = load_user_data()
    if user_id not in user_data:
        user_data[user_id] = {'username': update.effective_user.first_name, 'history': [], 'weight_history': []}
    
    context.user_data['current_day'] = day
    user_data[user_id]['current_session'] = {'day': day, 'exercises': [], 'start_time': datetime.now().isoformat()}
    save_user_data(user_data)
    
    program = TRAINING_PROGRAMS[day]
    exercises = program['exercises']
    exercises_list = "📝 <b>Полный список упражнений:</b>\n\n"
    for i, exercise in enumerate(exercises, 1):
        exercises_list += f"{i}. {exercise}\n"
    
    exercises_list += f"\nВсего упражнений: {len(exercises)}\n\n👇 Выберите упражнение для ввода результатов:"
    
    completed_exercises = user_data[user_id]['current_session'].get('completed_exercises', [])
    reply_markup = get_exercise_keyboard(day, completed_exercises, user_id)
    
    if update.message:
        update.message.reply_text(exercises_list, parse_mode='HTML', reply_markup=ReplyKeyboardRemove())
        update.message.reply_text("🎯 <b>Выберите упражнение:</b>", parse_mode='HTML', reply_markup=reply_markup)
    else:
        update.callback_query.edit_message_text("🎯 <b>Выберите упражнение:</b>", parse_mode='HTML', reply_markup=reply_markup)
    
    return CHOOSING_EXERCISE

def handle_exercise_selection(update: Update, context: CallbackContext):
    """Обработка выбора упражнения с таймерами в том же окне"""
    query = update.callback_query
    query.answer()
    
    user_id = str(update.effective_user.id)
    data = query.data
    
    if data == "progress":
        return show_current_progress(update, context)
    elif data == "finish":
        return finish_training_session(update, context)
    elif data == "reminders":
        return show_reminders(update, context)
    elif data == "stats":
        return show_detailed_statistics_menu(update, context)
    elif data.startswith("timer_"):
        return handle_timer_selection(update, context)
    elif data == "back_to_exercises":
        return show_exercise_list_after_input(update, context)
    elif data.startswith("ex_"):
        # Извлекаем индекс упражнения
        exercise_index = int(data.split("_")[1])
        context.user_data['current_exercise'] = exercise_index
        
        day = context.user_data.get('current_day')
        exercises = TRAINING_PROGRAMS[day]['exercises']
        exercise_name = exercises[exercise_index]
        
        # Получаем историю упражнения
        exercise_history = get_exercise_history(user_id, exercise_name)
        history_text = format_exercise_history(exercise_history)
        
        # Получаем рекомендации
        recommendations = generate_smart_recommendations(user_id, exercise_name)
        
        # Получаем ASCII-график
        full_history = get_full_exercise_history(user_id, exercise_name)
        ascii_chart = create_simple_ascii_chart(full_history)
        
        # Формируем расширенное сообщение с таймерами
        message_text = (
            f"💪 <b>Упражнение:</b> {exercise_name}\n\n"
            f"📊 <b>История выполнения:</b>\n{history_text}\n\n"
            f"{ascii_chart}\n\n"
            f"🎯 <b>Рекомендации:</b>\n{recommendations}\n\n"
        )
        
        message_text += (
            f"<b>Введите вес и количество повторений:</b>\n"
            f"<code>вес повторения</code>\n"
            f"Пример: <code>60 10</code>\n\n"
            f"<b>Или выберите таймер отдыха:</b>"
        )
        
        reply_markup = get_exercise_detail_keyboard()
        
        query.edit_message_text(
            message_text,
            parse_mode='HTML',
            reply_markup=reply_markup
        )
        
        return ENTERING_EXERCISE_DATA

def handle_timer_selection(update: Update, context: CallbackContext):
    """Обработка выбора таймера с возвратом в то же окно упражнения"""
    query = update.callback_query
    query.answer()
    
    data = query.data
    
    if data.startswith("timer_"):
        duration = int(data.split("_")[1])
        
        if duration == 90:
            timer_name = "1.5 минуты"
        elif duration == 120:
            timer_name = "2 минуты"
        elif duration == 180:
            timer_name = "3 минуты"
        elif duration == 300:
            timer_name = "5 минут"
        else:
            timer_name = f"{duration} секунд"
        
        # Запускаем таймер
        result = set_timer(update, context, duration, timer_name)
        
        # Показываем уведомление о запуске таймера
        query.message.reply_text(result)
        
        # Обновляем сообщение, чтобы показать, что таймер запущен
        current_message = query.message.text
        if "⏰ Таймер" not in current_message:
            updated_message = current_message + f"\n\n⏰ <b>Таймер {timer_name} запущен!</b>"
        else:
            # Если таймер уже был запущен, заменяем старую запись
            lines = current_message.split('\n')
            # Удаляем последние строки, содержащие информацию о таймере
            while lines and "⏰ Таймер" in lines[-1]:
                lines.pop()
            updated_message = '\n'.join(lines) + f"\n\n⏰ <b>Таймер {timer_name} запущен!</b>"
        
        try:
            query.edit_message_text(
                updated_message,
                parse_mode='HTML',
                reply_markup=query.message.reply_markup
            )
        except Exception as e:
            print(f"⚠️ Не удалось обновить сообщение: {e}")
        
        return ENTERING_EXERCISE_DATA

def handle_exercise_input(update: Update, context: CallbackContext):
    """Обработка ввода данных упражнения с возвратом к тому же интерфейсу"""
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()
    user_data = load_user_data()
    
    if user_id not in user_data or 'current_session' not in user_data[user_id]:
        update.message.reply_text("❌ Сессия тренировки не найдена. Начните заново: /train")
        return ConversationHandler.END
    
    current_session = user_data[user_id]['current_session']
    day = current_session['day']
    exercise_index = context.user_data.get('current_exercise')
    exercises_list = TRAINING_PROGRAMS[day]['exercises']
    exercise_name = exercises_list[exercise_index]
    
    try:
        parts = text.split()
        if len(parts) != 2:
            raise ValueError("Нужно ввести два числа")
        weight = float(parts[0])
        reps = int(parts[1])
        if weight <= 0 or reps <= 0:
            raise ValueError("Числа должны быть положительными")
    except ValueError as e:
        update.message.reply_text(f"❌ Неверный формат: {e}\n\nВведите в формате: <code>вес повторения</code>\nПример: <code>60 10</code>", parse_mode='HTML')
        return ENTERING_EXERCISE_DATA
    
    # Сохраняем результат текущего упражнения
    exercise_data = {
        'name': exercise_name,
        'weight': weight,
        'reps': reps,
        'timestamp': datetime.now().isoformat()
    }
    
    existing_index = None
    for i, ex in enumerate(current_session['exercises']):
        if ex['name'] == exercise_name:
            existing_index = i
            break
    
    if existing_index is not None:
        current_session['exercises'][existing_index] = exercise_data
    else:
        current_session['exercises'].append(exercise_data)
    
    if 'completed_exercises' not in current_session:
        current_session['completed_exercises'] = []
    if exercise_index not in current_session['completed_exercises']:
        current_session['completed_exercises'].append(exercise_index)
    
    save_user_data(user_data)
    
    # Добавляем сравнение с предыдущим результатом
    # ИСПРАВЛЕНИЕ: проверяем, что exercise_history не None
    exercise_history = get_exercise_history(user_id, exercise_name)
    previous_history = []
    if exercise_history is not None:
        previous_history = [h for h in exercise_history if h['weight'] != weight or h['reps'] != reps]
    progress_text = get_progress_comparison(weight, reps, previous_history)
    
    # Показываем обновленное сообщение с тем же интерфейсом
    day = context.user_data.get('current_day')
    exercises = TRAINING_PROGRAMS[day]['exercises']
    exercise_name = exercises[exercise_index]
    
    # Обновляем историю
    exercise_history = get_exercise_history(user_id, exercise_name)
    history_text = format_exercise_history(exercise_history)
    
    # Получаем рекомендации
    recommendations = generate_smart_recommendations(user_id, exercise_name)
    
    # Получаем ASCII-график
    full_history = get_full_exercise_history(user_id, exercise_name)
    ascii_chart = create_simple_ascii_chart(full_history)
    
    # Формируем сообщение
    message_text = (
        f"💪 <b>Упражнение:</b> {exercise_name}\n\n"
        f"✅ <b>Сохранено:</b> {weight}кг × {reps}повт.\n"
        f"{progress_text}\n\n"
        f"📊 <b>История выполнения:</b>\n{history_text}\n\n"
        f"{ascii_chart}\n\n"
        f"🎯 <b>Рекомендации:</b>\n{recommendations}\n\n"
    )
    
    message_text += (
        f"<b>Введите вес и количество повторений:</b>\n"
        f"<code>вес повторения</code>\n"
        f"Пример: <code>60 10</code>\n\n"
        f"<b>Или выберите таймер отдыха:</b>"
    )
    
    reply_markup = get_exercise_detail_keyboard()
    
    update.message.reply_text(
        message_text,
        parse_mode='HTML',
        reply_markup=reply_markup
    )
    
    return ENTERING_EXERCISE_DATA

def skip_exercise(update: Update, context: CallbackContext):
    """Пропуск упражнения с возвратом к списку"""
    user_id = str(update.effective_user.id)
    user_data = load_user_data()
    
    if user_id not in user_data or 'current_session' not in user_data[user_id]:
        update.message.reply_text("❌ Сессия тренировки не найдена. Начните заново: /train")
        return ConversationHandler.END
    
    current_session = user_data[user_id]['current_session']
    day = current_session['day']
    exercise_index = context.user_data.get('current_exercise')
    exercises_list = TRAINING_PROGRAMS[day]['exercises']
    exercise_name = exercises_list[exercise_index]
    
    update.message.reply_text(f"⏭️ Упражнение пропущено: {exercise_name}")
    return show_exercise_list_after_input(update, context)

def show_exercise_list_after_input(update: Update, context: CallbackContext):
    """Показывает список упражнений после ввода данных"""
    user_id = str(update.effective_user.id)
    user_data = load_user_data()
    day = context.user_data.get('current_day')
    
    if user_id in user_data and 'current_session' in user_data[user_id]:
        completed_exercises = user_data[user_id]['current_session'].get('completed_exercises', [])
    else:
        completed_exercises = []
    
    reply_markup = get_exercise_keyboard(day, completed_exercises, user_id)
    update.message.reply_text("🎯 <b>Выберите упражнение:</b>", parse_mode='HTML', reply_markup=reply_markup)
    return CHOOSING_EXERCISE

def show_current_progress(update: Update, context: CallbackContext):
    """Показывает текущий прогресс тренировки"""
    user_id = str(update.effective_user.id)
    user_data = load_user_data()
    
    if user_id not in user_data or 'current_session' not in user_data[user_id]:
        if update.callback_query:
            update.callback_query.message.reply_text("❌ Активная тренировка не найдена.")
        return CHOOSING_EXERCISE
    
    current_session = user_data[user_id]['current_session']
    day = current_session['day']
    progress_text = f"📊 <b>Текущий прогресс ({day}):</b>\n\n"
    
    if current_session['exercises']:
        for i, exercise in enumerate(current_session['exercises'], 1):
            progress_text += f"{i}. {exercise['name']}: {exercise['weight']}кг × {exercise['reps']}повт.\n"
    else:
        progress_text += "Пока нет выполненных упражнений.\n"
    
    total_exercises = len(TRAINING_PROGRAMS[day]['exercises'])
    completed_count = len(current_session['exercises'])
    progress_text += f"\n✅ Выполнено: {completed_count}/{total_exercises}"
    
    if update.callback_query:
        update.callback_query.message.reply_text(progress_text, parse_mode='HTML')
        # Возвращаем к тому же интерфейсу упражнения
        exercise_index = context.user_data.get('current_exercise')
        if exercise_index is not None:
            day = context.user_data.get('current_day')
            exercises = TRAINING_PROGRAMS[day]['exercises']
            exercise_name = exercises[exercise_index]
            
            user_id = str(update.effective_user.id)
            exercise_history = get_exercise_history(user_id, exercise_name)
            history_text = format_exercise_history(exercise_history)
            recommendations = generate_smart_recommendations(user_id, exercise_name)
            full_history = get_full_exercise_history(user_id, exercise_name)
            ascii_chart = create_simple_ascii_chart(full_history)
            
            message_text = (
                f"💪 <b>Упражнение:</b> {exercise_name}\n\n"
                f"📊 <b>История выполнения:</b>\n{history_text}\n\n"
                f"{ascii_chart}\n\n"
                f"🎯 <b>Рекомендации:</b>\n{recommendations}\n\n"
                f"<b>Введите вес и количество повторений:</b>\n"
                f"<code>вес повторения</code>\n"
                f"Пример: <code>60 10</code>\n\n"
                f"<b>Или выберите таймер отдыха:</b>"
            )
            
            reply_markup = get_exercise_detail_keyboard()
            update.callback_query.message.reply_text(message_text, parse_mode='HTML', reply_markup=reply_markup)
    
    return ENTERING_EXERCISE_DATA

def show_reminders(update: Update, context: CallbackContext):
    """Показывает умные напоминания"""
    user_id = str(update.effective_user.id)
    reminders = check_workout_reminders(user_id)
    
    if reminders:
        update.callback_query.message.reply_text(reminders, parse_mode='HTML')
    else:
        update.callback_query.message.reply_text("✅ Все отлично! Продолжайте в том же духе!", parse_mode='HTML')
    
    # Возвращаем к тому же интерфейсу упражнения
    exercise_index = context.user_data.get('current_exercise')
    if exercise_index is not None:
        day = context.user_data.get('current_day')
        exercises = TRAINING_PROGRAMS[day]['exercises']
        exercise_name = exercises[exercise_index]
        
        user_id = str(update.effective_user.id)
        exercise_history = get_exercise_history(user_id, exercise_name)
        history_text = format_exercise_history(exercise_history)
        recommendations = generate_smart_recommendations(user_id, exercise_name)
        full_history = get_full_exercise_history(user_id, exercise_name)
        ascii_chart = create_simple_ascii_chart(full_history)
        
        message_text = (
            f"💪 <b>Упражнение:</b> {exercise_name}\n\n"
            f"📊 <b>История выполнения:</b>\n{history_text}\n\n"
            f"{ascii_chart}\n\n"
            f"🎯 <b>Рекомендации:</b>\n{recommendations}\n\n"
            f"<b>Введите вес и количество повторений:</b>\n"
            f"<code>вес повторения</code>\n"
            f"Пример: <code>60 10</code>\n\n"
            f"<b>Или выберите таймер отдыха:</b>"
        )
        
        reply_markup = get_exercise_detail_keyboard()
        update.callback_query.message.reply_text(message_text, parse_mode='HTML', reply_markup=reply_markup)
    
    return ENTERING_EXERCISE_DATA

def show_detailed_statistics_menu(update: Update, context: CallbackContext):
    """Показывает меню детальной статистики"""
    user_id = str(update.effective_user.id)
    day = context.user_data.get('current_day')
    
    # Создаем клавиатуру со всеми упражнениями для статистики
    exercises = TRAINING_PROGRAMS[day]['exercises']
    keyboard = []
    
    for i, exercise in enumerate(exercises):
        keyboard.append([InlineKeyboardButton(
            f"{i+1}. {exercise}", 
            callback_data=f"stat_{i}"
        )])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_exercises")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.callback_query.message.reply_text(
        "📈 <b>Выберите упражнение для просмотра детальной статистики:</b>",
        parse_mode='HTML',
        reply_markup=reply_markup
    )

def show_exercise_statistics(update: Update, context: CallbackContext):
    """Показывает детальную статистику по выбранному упражнению"""
    query = update.callback_query
    query.answer()
    
    user_id = str(update.effective_user.id)
    data = query.data
    
    if data == "back_to_exercises":
        # Возвращаем к интерфейсу упражнения
        exercise_index = context.user_data.get('current_exercise')
        if exercise_index is not None:
            day = context.user_data.get('current_day')
            exercises = TRAINING_PROGRAMS[day]['exercises']
            exercise_name = exercises[exercise_index]
            
            exercise_history = get_exercise_history(user_id, exercise_name)
            history_text = format_exercise_history(exercise_history)
            recommendations = generate_smart_recommendations(user_id, exercise_name)
            full_history = get_full_exercise_history(user_id, exercise_name)
            ascii_chart = create_simple_ascii_chart(full_history)
            
            message_text = (
                f"💪 <b>Упражнение:</b> {exercise_name}\n\n"
                f"📊 <b>История выполнения:</b>\n{history_text}\n\n"
                f"{ascii_chart}\n\n"
                f"🎯 <b>Рекомендации:</b>\n{recommendations}\n\n"
                f"<b>Введите вес и количество повторений:</b>\n"
                f"<code>вес повторения</code>\n"
                f"Пример: <code>60 10</code>\n\n"
                f"<b>Или выберите таймер отдыха:</b>"
            )
            
            reply_markup = get_exercise_detail_keyboard()
            query.edit_message_text(
                message_text,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        return ENTERING_EXERCISE_DATA
    
    if data.startswith("stat_"):
        exercise_index = int(data.split("_")[1])
        day = context.user_data.get('current_day')
        exercises = TRAINING_PROGRAMS[day]['exercises']
        exercise_name = exercises[exercise_index]
        
        # Получаем детальную статистику
        stats = get_detailed_exercise_stats(user_id, exercise_name)
        stats_text = format_detailed_stats(stats, exercise_name)
        
        # Получаем ASCII-график
        full_history = get_full_exercise_history(user_id, exercise_name)
        ascii_chart = create_simple_ascii_chart(full_history)
        
        # Получаем рекомендации
        recommendations = generate_smart_recommendations(user_id, exercise_name)
        
        full_message = f"{stats_text}\n\n{ascii_chart}\n\n🎯 <b>Рекомендации:</b>\n{recommendations}"
        
        # Создаем клавиатуру для возврата
        keyboard = [[InlineKeyboardButton("🔙 Назад к статистике", callback_data="stats")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        query.edit_message_text(
            full_message,
            parse_mode='HTML',
            reply_markup=reply_markup
        )

def finish_training_session(update: Update, context: CallbackContext):
    """Завершение тренировки с предложением взвеситься"""
    user_id = str(update.effective_user.id)
    user_data = load_user_data()
    
    if user_id not in user_data or 'current_session' not in user_data[user_id]:
        if update.callback_query:
            update.callback_query.message.reply_text("❌ Активная тренировка не найдена.")
        return ConversationHandler.END
    
    current_session = user_data[user_id]['current_session']
    day = current_session['day']
    
    if not current_session['exercises']:
        if update.callback_query:
            update.callback_query.message.reply_text("❌ Вы не выполнили ни одного упражнения. Тренировка отменена.")
        del user_data[user_id]['current_session']
        save_user_data(user_data)
        return ConversationHandler.END
    
    user_data[user_id]['history'].append(current_session)
    del user_data[user_id]['current_session']
    save_user_data(user_data)
    
    summary = "🎉 Тренировка завершена! 🎉\n\n<b>Ваши результаты:</b>\n"
    for i, exercise in enumerate(current_session['exercises'], 1):
        summary += f"{i}. {exercise['name']}: {exercise['weight']}кг × {exercise['reps']}повт.\n"
    
    total_exercises = len(TRAINING_PROGRAMS[day]['exercises'])
    completed_count = len(current_session['exercises'])
    summary += f"\n💪 Выполнено: {completed_count}/{total_exercises} упражнений\n\n"
    
    # Добавляем предложение взвеситься
    weight_history = get_weight_history(user_id)
    if weight_history:
        last_weight = weight_history[-1]['weight']
        summary += f"⚖️ Ваш последний вес: {last_weight}кг\n"
    
    summary += "\nХотите записать текущий вес?\nВведите вес в килограммах или /skip чтобы пропустить"
    
    if update.callback_query:
        update.callback_query.message.reply_text(summary, parse_mode='HTML')
    else:
        update.message.reply_text(summary, parse_mode='HTML')
    
    return WEIGHING

def handle_weight_input(update: Update, context: CallbackContext):
    """Обработка ввода веса"""
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()
    
    try:
        weight = float(text)
        if weight <= 0 or weight > 300:
            raise ValueError("Некорректный вес")
    except ValueError:
        update.message.reply_text("❌ Пожалуйста, введите корректный вес в килограммах (например: 75.5)")
        return WEIGHING
    
    # Сохраняем вес
    weight_record = save_weight(user_id, weight)
    
    # Получаем историю для анализа
    weight_history = get_weight_history(user_id)
    progress_text = get_weight_progress(weight_history)
    
    response = (
        f"✅ Вес сохранен: {weight}кг\n"
        f"{progress_text}\n\n"
        f"{format_weight_history(weight_history)}"
    )
    
    update.message.reply_text(response)
    
    # Завершаем диалог
    keyboard = [["/train", "/progress"], ["/stats", "/help"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    update.message.reply_text("🏁 Тренировка завершена!", reply_markup=reply_markup)
    
    return ConversationHandler.END

def skip_weight(update: Update, context: CallbackContext):
    """Пропуск взвешивания"""
    update.message.reply_text("⚖️ Взвешивание пропущено")
    
    # Завершаем диалог
    keyboard = [["/train", "/progress"], ["/stats", "/help"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    update.message.reply_text("🏁 Тренировка завершена!", reply_markup=reply_markup)
    
    return ConversationHandler.END

def weight_command(update: Update, context: CallbackContext):
    """Команда /weight - запись веса вне тренировки"""
    user_id = str(update.effective_user.id)
    weight_history = get_weight_history(user_id)
    
    if weight_history:
        last_weight = weight_history[-1]['weight']
        update.message.reply_text(
            f"⚖️ Ваш последний вес: {last_weight}кг\n\n"
            f"Введите текущий вес в килограммах:",
            parse_mode='HTML'
        )
    else:
        update.message.reply_text(
            "⚖️ Введите ваш вес в килограммах:",
            parse_mode='HTML'
        )
    
    return WEIGHING

def view_progress(update: Update, context: CallbackContext):
    """Команда /progress - просмотр истории тренировок и веса"""
    user_id = str(update.effective_user.id)
    user_data = load_user_data()
    
    if user_id not in user_data or not user_data[user_id].get('history'):
        update.message.reply_text("📊 У вас пока нет записей о тренировках.\nНачните первую тренировку: /train")
        return
    
    history = user_data[user_id]['history']
    response = "📊 <b>История ваших тренировок:</b>\n\n"
    
    for i, session in enumerate(history[-5:], 1):
        session_date = datetime.fromisoformat(session['start_time']).strftime('%d.%m.%Y')
        response += f"<b>Тренировка {i} ({session['day']}) - {session_date}:</b>\n"
        for j, exercise in enumerate(session['exercises'][:3], 1):
            response += f"  {j}. {exercise['name']}: {exercise['weight']}кг × {exercise['reps']}повт.\n"
        if len(session['exercises']) > 3:
            response += f"  ... и ещё {len(session['exercises']) - 3} упражнений\n"
        response += "\n"
    
    response += f"Всего тренировок: {len(history)}\n\n"
    
    # Добавляем историю веса
    weight_history = get_weight_history(user_id)
    if weight_history:
        response += format_weight_history(weight_history)
        response += f"\n\n{get_weight_progress(weight_history)}"
    
    update.message.reply_text(response, parse_mode='HTML')

def view_stats(update: Update, context: CallbackContext):
    """Команда /stats - статистика прогресса"""
    user_id = str(update.effective_user.id)
    user_data = load_user_data()
    
    if user_id not in user_data or not user_data[user_id].get('history'):
        update.message.reply_text("📈 У вас пока нет данных для статистики.\nНачните первую тренировку: /train")
        return
    
    history = user_data[user_id]['history']
    stats_text = "📈 <b>Ваша статистика:</b>\n\n"
    stats_text += f"Всего тренировок: <b>{len(history)}</b>\n"
    
    day_a_count = sum(1 for session in history if session['day'] == 'День А')
    day_b_count = sum(1 for session in history if session['day'] == 'День Б')
    stats_text += f"День А: <b>{day_a_count}</b> тренировок\n"
    stats_text += f"День Б: <b>{day_b_count}</b> тренировок\n\n"
    
    # Добавляем статистику веса
    weight_history = get_weight_history(user_id)
    if weight_history:
        current_weight = weight_history[-1]['weight']
        stats_text += f"⚖️ Текущий вес: <b>{current_weight}кг</b>\n"
        if len(weight_history) > 1:
            first_weight = weight_history[0]['weight']
            difference = current_weight - first_weight
            if difference > 0:
                stats_text += f"📈 Изменение веса: <b>+{difference:.1f}кг</b>\n"
            elif difference < 0:
                stats_text += f"📉 Изменение веса: <b>{difference:.1f}кг</b>\n"
            else:
                stats_text += f"⚖️ Вес не изменился\n"
    
    if len(history) >= 2:
        stats_text += "🔄 <b>Последние тренировки сохранены!</b>\n"
    stats_text += "\nПродолжайте в том же духе! 💪"
    update.message.reply_text(stats_text, parse_mode='HTML')

def help_command(update: Update, context: CallbackContext):
    """Команда /help - справка"""
    help_text = """
🤖 <b>Помощь по использованию бота</b>

<b>Основные команды:</b>
/train - Начать новую тренировку
/progress - Посмотреть историю тренировок и веса
/stats - Статистика прогресса
/weight - Записать текущий вес
/help - Эта справка

<b>Новые возможности:</b>
• ⏱ <b>Таймеры отдыха</b> - 1.5, 2, 3, 5 минут для отдыха между подходами
• ⚖️ <b>Трекер веса</b> - автоматическое предложение взвеситься после тренировки
• 📊 <b>Графики прогресса</b> - ASCII-визуализация ваших результатов
• 🎯 <b>Умные рекомендации</b> - AI-советы на основе вашей истории

<b>Как работать с ботом:</b>
1. Нажмите /train
2. Выберите день тренировки
3. Выберите упражнение - откроется окно с таймерами
4. Вводите данные упражнений или запускайте таймеры отдыха
5. После тренировки запишите вес
6. Следите за прогрессом в /progress

<b>Таймеры отдыха:</b>
• ⏱ 1.5 мин - для суперсетов и легких упражнений
• ⏱ 3 мин - для базовых упражнений и тяжелых подходов
• ⏱ 5 мин - для максимальных весов

💡 <b>Рекомендация:</b> Чередуйте дни по схеме:
Неделя 1: А-Б-А, Неделя 2: Б-А-Б
    """
    update.message.reply_text(help_text, parse_mode='HTML')

def cancel(update: Update, context: CallbackContext):
    """Отмена текущей операции"""
    user_id = str(update.effective_user.id)
    user_data = load_user_data()
    
    if user_id in user_data and 'current_session' in user_data[user_id]:
        del user_data[user_id]['current_session']
        save_user_data(user_data)
    
    update.message.reply_text("❌ Тренировка отменена.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

def error_handler(update: Update, context: CallbackContext):
    """Обработка ошибок"""
    logger.error(f"Ошибка: {context.error}", exc_info=context.error)
    if update and update.effective_message:
        update.effective_message.reply_text("❌ Произошла ошибка. Попробуйте еще раз или начните заново: /start")

# ========== ЗАПУСК БОТА ==========
def main():
    """Основная функция запуска бота"""
    global updater
    
    print("🤖 Бот запускается на Railway...")
    print("⏹️ Для остановки используйте панель Railway")
    
    # Проверяем токен
    if not BOT_TOKEN:
        print("❌ Не могу запустить бота без BOT_TOKEN")
        return
    
    try:
        # Создаем updater с обработкой конфликтов
        updater = Updater(
            BOT_TOKEN, 
            use_context=True,
            request_kwargs={
                'read_timeout': 10, 
                'connect_timeout': 10
            }
        )
        dispatcher = updater.dispatcher
        
        # Обработчик диалога тренировки
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler('train', start_training_command),
                CommandHandler('weight', weight_command)
            ],
            states={
                CHOOSING_DAY: [MessageHandler(Filters.regex('^(День А|День Б)$'), show_exercise_list)],
                CHOOSING_EXERCISE: [
                    CallbackQueryHandler(handle_exercise_selection, pattern='^(ex_|progress|finish|reminders|stats|timer_|back_to_exercises)'),
                    CallbackQueryHandler(show_exercise_statistics, pattern='^(stat_)')
                ],
                ENTERING_EXERCISE_DATA: [
                    MessageHandler(Filters.text & ~Filters.command, handle_exercise_input),
                    CommandHandler('skip', skip_exercise),
                    CallbackQueryHandler(handle_exercise_selection, pattern='^(progress|finish|reminders|stats|timer_|back_to_exercises)')
                ],
                WEIGHING: [
                    MessageHandler(Filters.text & ~Filters.command, handle_weight_input),
                    CommandHandler('skip', skip_weight)
                ]
            },
            fallbacks=[CommandHandler('cancel', cancel)],
            per_chat=True,
            per_user=True,
            per_message=False
        )
        
        # Регистрируем обработчики
        dispatcher.add_handler(CommandHandler("start", start))
        dispatcher.add_handler(CommandHandler("progress", view_progress))
        dispatcher.add_handler(CommandHandler("stats", view_stats))
        dispatcher.add_handler(CommandHandler("help", help_command))
        dispatcher.add_handler(CommandHandler("cancel", cancel))
        dispatcher.add_handler(conv_handler)
        dispatcher.add_error_handler(error_handler)
        
        # Запускаем бота с правильными параметрами для Railway
        print("✅ Бот успешно запущен и готов к работе!")
        
        updater.start_polling(
            drop_pending_updates=True,  # Игнорируем старые сообщения при перезапуске
            timeout=20,
            allowed_updates=['message', 'callback_query']
        )
        
        # Ждем завершения
        updater.idle()
        
    except Exception as e:
        print(f"❌ Ошибка при запуске бота: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
