import logging
import json
import os
import signal
import sys
import asyncio
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler, 
    MessageHandler, 
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler
)

# ========== НАСТРОЙКА ЛОГГИРОВАНИЯ ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.environ.get('BOT_TOKEN')

if not BOT_TOKEN:
    print("❌ ОШИБКА: BOT_TOKEN не найден!")
    sys.exit(1)

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
    for i, record in enumerate(weight_history[-5:], 1):
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
async def timer_callback(context: ContextTypes.DEFAULT_TYPE):
    """Колбэк для завершения таймера"""
    job = context.job
    chat_id = job.context['chat_id']
    timer_name = job.context['timer_name']
    
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🎯 {timer_name} завершен! Можно делать следующий подход! 💪"
        )
        print(f"✅ Уведомление о завершении таймера отправлено в чат {chat_id}")
    except Exception as e:
        print(f"❌ Ошибка отправки уведомления таймера: {e}")

def set_timer(update: Update, context: ContextTypes.DEFAULT_TYPE, duration: int, timer_name: str):
    """Устанавливает таймер через job queue"""
    chat_id = update.effective_message.chat_id
    
    timer_job_context = {'chat_id': chat_id, 'timer_name': timer_name}
    
    # Запускаем основной таймер
    context.job_queue.run_once(
        timer_callback,
        duration,
        context=timer_job_context,
        name=f"timer_end_{chat_id}"
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
                if limit and len(exercise_history) >= limit:
                    return exercise_history
    
    return exercise_history

def get_full_exercise_history(user_id, exercise_name):
    return get_exercise_history(user_id, exercise_name, limit=None)

def format_exercise_history(history):
    if not history:
        return "📝 Ранее не выполнялось"
    
    lines = []
    for i, record in enumerate(history, 1):
        lines.append(f"{i}. {record['date']} ({record['day']}): {record['weight']}кг × {record['reps']}повт.")
    
    return "\n".join(lines)

def generate_smart_recommendations(user_id, exercise_name):
    history = get_full_exercise_history(user_id, exercise_name)
    if not history or len(history) < 3:
        return "💡 Продолжайте собирать данные для персонализированных рекомендаций"
    
    return "💪 Продолжайте в том же духе! Ваш прогресс стабилен"

def check_workout_reminders(user_id):
    user_data = load_user_data()
    
    if user_id not in user_data or not user_data[user_id].get('history'):
        return "💡 Начните первую тренировку! Используйте /train"
    
    return None

# ========== ФУНКЦИИ ИНТЕРФЕЙСА ==========
def get_exercise_keyboard(day, completed_exercises, user_id=None):
    exercises = TRAINING_PROGRAMS[day]['exercises']
    keyboard = []
    
    for i, exercise in enumerate(exercises):
        status = "✅" if i in completed_exercises else "◻️"
        
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
    
    keyboard.append([
        InlineKeyboardButton("📊 Прогресс", callback_data="progress"),
        InlineKeyboardButton("🎯 Рекомендации", callback_data="reminders")
    ])
    keyboard.append([
        InlineKeyboardButton("🏁 Завершить", callback_data="finish")
    ])
    
    return InlineKeyboardMarkup(keyboard)

def get_exercise_detail_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("⏱ 1.5 мин", callback_data="timer_90"),
            InlineKeyboardButton("⏱ 3 мин", callback_data="timer_180")
        ],
        [
            InlineKeyboardButton("🔙 К списку упражнений", callback_data="back_to_exercises"),
            InlineKeyboardButton("🏁 Завершить", callback_data="finish")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# ========== ОСНОВНЫЕ ФУНКЦИИ БОТА ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_text = f"""
🤖 Привет, {user.first_name}!

🏋️‍♂️ Добро пожаловать в трекер тренировок!

<b>Основные команды:</b>
/train - Начать новую тренировку
/progress - Посмотреть историю тренировок
/stats - Статистика прогресса
/weight - Записать текущий вес
/help - Помощь по использованию
    """
    await update.message.reply_text(welcome_text, parse_mode='HTML')

async def start_training_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await choose_training_day(update, context)

async def choose_training_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["День А", "День Б"], ["/cancel"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    
    programs_info = "📋 <b>Программы тренировок:</b>\n\n"
    for day, program in TRAINING_PROGRAMS.items():
        programs_info += f"<b>{day}</b>\n{program['description']}\n<i>Упражнений: {len(program['exercises'])}</i>\n\n"
    
    programs_info += "Выберите день тренировки:"
    await update.message.reply_text(programs_info, parse_mode='HTML', reply_markup=reply_markup)
    return CHOOSING_DAY

async def show_exercise_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        day = update.message.text
    else:
        day = context.user_data.get('current_day')
    
    user_id = str(update.effective_user.id)
    
    if day not in TRAINING_PROGRAMS:
        await update.message.reply_text("❌ Пожалуйста, выберите день из предложенных вариантов", reply_markup=ReplyKeyboardRemove())
        return await choose_training_day(update, context)
    
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
        await update.message.reply_text(exercises_list, parse_mode='HTML', reply_markup=ReplyKeyboardRemove())
        await update.message.reply_text("🎯 <b>Выберите упражнение:</b>", parse_mode='HTML', reply_markup=reply_markup)
    else:
        await update.callback_query.edit_message_text("🎯 <b>Выберите упражнение:</b>", parse_mode='HTML', reply_markup=reply_markup)
    
    return CHOOSING_EXERCISE

async def handle_exercise_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = str(update.effective_user.id)
    data = query.data
    
    if data == "progress":
        return await show_current_progress(update, context)
    elif data == "finish":
        return await finish_training_session(update, context)
    elif data == "reminders":
        return await show_reminders(update, context)
    elif data.startswith("timer_"):
        return await handle_timer_selection(update, context)
    elif data == "back_to_exercises":
        return await show_exercise_list_after_input(update, context)
    elif data.startswith("ex_"):
        exercise_index = int(data.split("_")[1])
        context.user_data['current_exercise'] = exercise_index
        
        day = context.user_data.get('current_day')
        exercises = TRAINING_PROGRAMS[day]['exercises']
        exercise_name = exercises[exercise_index]
        
        exercise_history = get_exercise_history(user_id, exercise_name)
        history_text = format_exercise_history(exercise_history)
        
        recommendations = generate_smart_recommendations(user_id, exercise_name)
        
        message_text = (
            f"💪 <b>Упражнение:</b> {exercise_name}\n\n"
            f"📊 <b>История выполнения:</b>\n{history_text}\n\n"
            f"🎯 <b>Рекомендации:</b>\n{recommendations}\n\n"
        )
        
        message_text += (
            f"<b>Введите вес и количество повторений:</b>\n"
            f"<code>вес повторения</code>\n"
            f"Пример: <code>60 10</code>\n\n"
            f"<b>Или выберите таймер отдыха:</b>"
        )
        
        reply_markup = get_exercise_detail_keyboard()
        
        await query.edit_message_text(
            message_text,
            parse_mode='HTML',
            reply_markup=reply_markup
        )
        
        return ENTERING_EXERCISE_DATA

async def handle_timer_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith("timer_"):
        duration = int(data.split("_")[1])
        
        if duration == 90:
            timer_name = "1.5 минуты"
        elif duration == 180:
            timer_name = "3 минуты"
        else:
            timer_name = f"{duration} секунд"
        
        result = set_timer(update, context, duration, timer_name)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=result
        )
        
        return ENTERING_EXERCISE_DATA

async def handle_exercise_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()
    user_data = load_user_data()
    
    if user_id not in user_data or 'current_session' not in user_data[user_id]:
        await update.message.reply_text("❌ Сессия тренировки не найдена. Начните заново: /train")
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
        await update.message.reply_text(f"❌ Неверный формат: {e}\n\nВведите в формате: <code>вес повторения</code>\nПример: <code>60 10</code>", parse_mode='HTML')
        return ENTERING_EXERCISE_DATA
    
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
    
    await update.message.reply_text(f"✅ Сохранено: {weight}кг × {reps}повт.")
    
    return await show_exercise_list_after_input(update, context)

async def show_exercise_list_after_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_data = load_user_data()
    day = context.user_data.get('current_day')
    
    if user_id in user_data and 'current_session' in user_data[user_id]:
        completed_exercises = user_data[user_id]['current_session'].get('completed_exercises', [])
    else:
        completed_exercises = []
    
    reply_markup = get_exercise_keyboard(day, completed_exercises, user_id)
    
    if update.message:
        await update.message.reply_text("🎯 <b>Выберите упражнение:</b>", parse_mode='HTML', reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.edit_message_text("🎯 <b>Выберите упражнение:</b>", parse_mode='HTML', reply_markup=reply_markup)
    
    return CHOOSING_EXERCISE

async def show_current_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_data = load_user_data()
    
    if user_id not in user_data or 'current_session' not in user_data[user_id]:
        if update.callback_query:
            await update.callback_query.message.reply_text("❌ Активная тренировка не найдена.")
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
        await update.callback_query.message.reply_text(progress_text, parse_mode='HTML')
    
    return ENTERING_EXERCISE_DATA

async def show_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    reminders = check_workout_reminders(user_id)
    
    if update.callback_query:
        if reminders:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=reminders,
                parse_mode='HTML'
            )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="✅ Все отлично! Продолжайте в том же духе!",
                parse_mode='HTML'
            )
    
    return ENTERING_EXERCISE_DATA

async def finish_training_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_data = load_user_data()
    
    if user_id not in user_data or 'current_session' not in user_data[user_id]:
        if update.callback_query:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Активная тренировка не найдена."
            )
        return ConversationHandler.END
    
    current_session = user_data[user_id]['current_session']
    day = current_session['day']
    
    if not current_session['exercises']:
        if update.callback_query:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Вы не выполнили ни одного упражнения. Тренировка отменена."
            )
        del user_data[user_id]['current_session']
        save_user_data(user_data)
        return ConversationHandler.END
    
    user_data[user_id]['history'].append(current_session)
    del user_data[user_id]['current_session']
    save_user_data(user_data)
    
    summary = "🎉 Тренировка завершена! 🎉\n\n<b>Ваши результаты:</b>\n"
    for i, exercise in enumerate(current_session['exercises'], 1):
        summary += f"{i}. {exercise['name']}: {exercise['weight']}кг × {exercise['reps']}повт.\n"
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=summary,
        parse_mode='HTML'
    )
    
    return ConversationHandler.END

async def view_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_data = load_user_data()
    
    if user_id not in user_data or not user_data[user_id].get('history'):
        await update.message.reply_text("📊 У вас пока нет записей о тренировках.\nНачните первую тренировку: /train")
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
    
    response += f"Всего тренировок: {len(history)}"
    await update.message.reply_text(response, parse_mode='HTML')

async def view_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_data = load_user_data()
    
    if user_id not in user_data or not user_data[user_id].get('history'):
        await update.message.reply_text("📈 У вас пока нет данных для статистики.\nНачните первую тренировку: /train")
        return
    
    history = user_data[user_id]['history']
    stats_text = "📈 <b>Ваша статистика:</b>\n\n"
    stats_text += f"Всего тренировок: <b>{len(history)}</b>\n"
    
    day_a_count = sum(1 for session in history if session['day'] == 'День А')
    day_b_count = sum(1 for session in history if session['day'] == 'День Б')
    stats_text += f"День А: <b>{day_a_count}</b> тренировок\n"
    stats_text += f"День Б: <b>{day_b_count}</b> тренировок\n"
    stats_text += "\nПродолжайте в том же духе! 💪"
    
    await update.message.reply_text(stats_text, parse_mode='HTML')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
🤖 <b>Помощь по использованию бота</b>

<b>Основные команды:</b>
/train - Начать новую тренировку
/progress - Посмотреть историю тренировок
/stats - Статистика прогресса
/weight - Записать текущий вес
/help - Эта справка

<b>Как работать с ботом:</b>
1. Нажмите /train
2. Выберите день тренировки
3. Выберите упражнение
4. Вводите данные упражнений
5. После тренировки завершите сессию
    """
    await update.message.reply_text(help_text, parse_mode='HTML')

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_data = load_user_data()
    
    if user_id in user_data and 'current_session' in user_data[user_id]:
        del user_data[user_id]['current_session']
        save_user_data(user_data)
    
    await update.message.reply_text("❌ Тренировка отменена.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}", exc_info=context.error)
    if update and update.effective_message:
        await update.effective_message.reply_text("❌ Произошла ошибка. Попробуйте еще раз или начните заново: /start")

# ========== ЗАПУСК БОТА ==========
def main():
    print("🤖 Бот запускается...")
    
    if not BOT_TOKEN:
        print("❌ Не могу запустить бота без BOT_TOKEN")
        return
    
    try:
        application = Application.builder().token(BOT_TOKEN).build()
        
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('train', start_training_command)],
            states={
                CHOOSING_DAY: [MessageHandler(filters.Regex('^(День А|День Б)$'), show_exercise_list)],
                CHOOSING_EXERCISE: [
                    CallbackQueryHandler(handle_exercise_selection, pattern='^(ex_|progress|finish|reminders|timer_|back_to_exercises)')
                ],
                ENTERING_EXERCISE_DATA: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_exercise_input),
                    CallbackQueryHandler(handle_exercise_selection, pattern='^(progress|finish|reminders|timer_|back_to_exercises)')
                ]
            },
            fallbacks=[CommandHandler('cancel', cancel)],
        )
        
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("progress", view_progress))
        application.add_handler(CommandHandler("stats", view_stats))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("cancel", cancel))
        application.add_handler(conv_handler)
        application.add_error_handler(error_handler)
        
        print("✅ Бот успешно запущен и готов к работе!")
        
        application.run_polling()
        
    except Exception as e:
        print(f"❌ Ошибка при запуске бота: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
