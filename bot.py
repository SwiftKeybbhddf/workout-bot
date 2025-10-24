import logging
import json
import os
import time
from datetime import datetime
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
import matplotlib.pyplot as plt
import io
import base64
from datetime import datetime, timedelta

def generate_progress_chart(user_id, exercise_name, days_back=30):
    """Генерирует график прогресса по упражнению"""
    try:
        history = get_exercise_history(user_id, exercise_name)
        if not history or len(history) < 2:
            return None
        
        # Фильтруем данные за последние days_back дней
        cutoff_date = datetime.now() - timedelta(days=days_back)
        filtered_history = [
            h for h in history 
            if datetime.strptime(h['date'], '%d.%m.%Y') >= cutoff_date
        ]
        
        if len(filtered_history) < 2:
            return None
            
        # Сортируем по дате
        filtered_history.sort(key=lambda x: datetime.strptime(x['date'], '%d.%m.%Y'))
        
        dates = [h['date'] for h in filtered_history]
        weights = [h['weight'] for h in filtered_history]
        reps = [h['reps'] for h in filtered_history]
        
        # Создаем график
        plt.figure(figsize=(10, 6))
        
        # График веса
        plt.subplot(2, 1, 1)
        plt.plot(dates, weights, 'o-', linewidth=2, markersize=8, color='#2E86AB')
        plt.title(f'📈 Прогресс: {exercise_name}', fontsize=14, fontweight='bold', pad=20)
        plt.ylabel('Вес (кг)', fontsize=12)
        plt.grid(True, alpha=0.3)
        plt.xticks(rotation=45)
        
        # График повторений
        plt.subplot(2, 1, 2)
        plt.plot(dates, reps, 's-', linewidth=2, markersize=6, color='#A23B72')
        plt.ylabel('Повторения', fontsize=12)
        plt.xlabel('Дата', fontsize=12)
        plt.grid(True, alpha=0.3)
        plt.xticks(rotation=45)
        
        plt.tight_layout()
        
        # Сохраняем в buffer
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', dpi=100, bbox_inches='tight')
        buffer.seek(0)
        plt.close()
        
        return buffer
        
    except Exception as e:
        print(f"Ошибка генерации графика: {e}")
        return None

def create_simple_ascii_chart(history):
    """Создает простой ASCII-график когда нет возможности сгенерировать изображение"""
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
# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

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
CHOOSING_DAY, CHOOSING_EXERCISE, ENTERING_EXERCISE_DATA = range(3)
DATA_FILE = 'user_data.json'

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

def get_exercise_keyboard(day, completed_exercises):
    """Создает клавиатуру для выбора упражнений"""
    exercises = TRAINING_PROGRAMS[day]['exercises']
    keyboard = []
    
    for i, exercise in enumerate(exercises):
        status = "✅" if i in completed_exercises else "◻️"
        keyboard.append([InlineKeyboardButton(f"{status} {i+1}. {exercise}", callback_data=f"ex_{i}")])
    
    keyboard.append([InlineKeyboardButton("📊 Посмотреть прогресс", callback_data="progress")])
    keyboard.append([InlineKeyboardButton("🏁 Завершить тренировку", callback_data="finish")])
    
    return InlineKeyboardMarkup(keyboard)

def start(update: Update, context: CallbackContext):
    """Команда /start - начало работы"""
    user = update.effective_user
    welcome_text = f"""
🤖 Привет, {user.first_name}!

🏋️‍♂️ Добро пожаловать в трекер тренировок!

Я помогу вам отслеживать прогресс по программе фуллбади 3 раза в неделю.

📋 Доступные команды:
/train - Начать новую тренировку
/progress - Посмотреть историю тренировок
/stats - Статистика прогресса
/help - Помощь по использованию
    """
    update.message.reply_text(welcome_text)

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
        user_data[user_id] = {'username': update.effective_user.first_name, 'history': []}
    
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
    reply_markup = get_exercise_keyboard(day, completed_exercises)
    
    if update.message:
        update.message.reply_text(exercises_list, parse_mode='HTML', reply_markup=ReplyKeyboardRemove())
        update.message.reply_text("🎯 <b>Выберите упражнение:</b>", parse_mode='HTML', reply_markup=reply_markup)
    else:
        update.callback_query.edit_message_text("🎯 <b>Выберите упражнение:</b>", parse_mode='HTML', reply_markup=reply_markup)
    
    return CHOOSING_EXERCISE

def handle_exercise_selection(update: Update, context: CallbackContext):
    """Обработка выбора упражнения"""
    query = update.callback_query
    query.answer()
    user_id = str(update.effective_user.id)
    data = query.data
    
    if data == "progress":
        return show_current_progress(update, context)
    elif data == "finish":
        return finish_training_session(update, context)
    elif data.startswith("ex_"):
        exercise_index = int(data.split("_")[1])
        context.user_data['current_exercise'] = exercise_index
        day = context.user_data.get('current_day')
        exercises = TRAINING_PROGRAMS[day]['exercises']
        exercise_name = exercises[exercise_index]
        
        query.edit_message_text(
            f"💪 <b>Упражнение:</b> {exercise_name}\n\nВведите вес и количество повторений:\n<code>вес повторения</code>\nПример: <code>60 10</code>\n\nИли нажмите /skip чтобы пропустить",
            parse_mode='HTML'
        )
        return ENTERING_EXERCISE_DATA

def handle_exercise_input(update: Update, context: CallbackContext):
    """Обработка ввода данных упражнения"""
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
    
    exercise_data = {'name': exercise_name, 'weight': weight, 'reps': reps, 'timestamp': datetime.now().isoformat()}
    
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
    update.message.reply_text(f"✅ Сохранено: {exercise_name}\nРезультат: {weight}кг × {reps}повт.\n\nВыберите следующее упражнение:")
    return show_exercise_list_after_input(update, context)

def skip_exercise(update: Update, context: CallbackContext):
    """Пропуск упражнения"""
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
    
    update.message.reply_text(f"⏭️ Упражнение пропущено: {exercise_name}\n\nВы можете вернуться к нему позже.")
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
    
    reply_markup = get_exercise_keyboard(day, completed_exercises)
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
        completed_exercises = current_session.get('completed_exercises', [])
        reply_markup = get_exercise_keyboard(day, completed_exercises)
        update.callback_query.message.reply_text("🎯 <b>Выберите упражнение:</b>", parse_mode='HTML', reply_markup=reply_markup)
    
    return CHOOSING_EXERCISE

def finish_training_session(update: Update, context: CallbackContext):
    """Завершение тренировки"""
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
    summary += f"\n💪 Выполнено: {completed_count}/{total_exercises} упражнений\n\nОтличная работа! Следующая тренировка через 1-2 дня."
    
    keyboard = [["/train", "/progress"], ["/stats", "/help"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    if update.callback_query:
        update.callback_query.message.reply_text(summary, parse_mode='HTML', reply_markup=reply_markup)
    else:
        update.message.reply_text(summary, parse_mode='HTML', reply_markup=reply_markup)
    
    return ConversationHandler.END

def view_progress(update: Update, context: CallbackContext):
    """Команда /progress - просмотр истории тренировок"""
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
    
    response += f"Всего тренировок: {len(history)}"
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
/progress - Посмотреть историю тренировок  
/stats - Статистика прогресса
/help - Эта справка

<b>Как работать с ботом:</b>
1. Нажмите /train
2. Выберите день тренировки
3. Просмотрите полный список упражнений
4. Выбирайте упражнения в любом порядке
5. Вводите данные в формате: <code>вес повторения</code>
6. Завершите тренировку когда закончите
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

def main():
    """Основная функция запуска бота"""
    print("🤖 Бот запускается на Railway...")
    print("⏹️ Для остановки используйте панель Railway")
    
    # Проверяем токен
    if not BOT_TOKEN:
        print("❌ Не могу запустить бота без BOT_TOKEN")
        return
    
    try:
        # Создаем updater с обработкой конфликтов
        updater = Updater(BOT_TOKEN, use_context=True)
        dispatcher = updater.dispatcher
        
        # Обработчик диалога тренировки
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('train', start_training_command)],
            states={
                CHOOSING_DAY: [MessageHandler(Filters.regex('^(День А|День Б)$'), show_exercise_list)],
                CHOOSING_EXERCISE: [CallbackQueryHandler(handle_exercise_selection, pattern='^(ex_|progress|finish)')],
                ENTERING_EXERCISE_DATA: [
                    MessageHandler(Filters.text & ~Filters.command, handle_exercise_input),
                    CommandHandler('skip', skip_exercise)
                ],
            },
            fallbacks=[CommandHandler('cancel', cancel)],
        )
        
        # Регистрируем обработчики
        dispatcher.add_handler(CommandHandler("start", start))
        dispatcher.add_handler(CommandHandler("progress", view_progress))
        dispatcher.add_handler(CommandHandler("stats", view_stats))
        dispatcher.add_handler(CommandHandler("help", help_command))
        dispatcher.add_handler(CommandHandler("cancel", cancel))
        dispatcher.add_handler(conv_handler)
        dispatcher.add_error_handler(error_handler)
        
        # Запускаем бота
        print("✅ Бот успешно запущен и готов к работе!")
        updater.start_polling()
        updater.idle()
        
    except Exception as e:
        print(f"❌ Ошибка при запуске бота: {e}")

if __name__ == '__main__':
    main()
