
import logging
import json
import os
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
# Для работы на Railway - простой HTTP сервер
from flask import Flask
import threading

app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Workout Bot is running!"

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

# Запускаем Flask в отдельном потоке
flask_thread = threading.Thread(target=run_flask)
flask_thread.daemon = True
flask_thread.start()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Загрузка конфигурации
try:
    from config import BOT_TOKEN, TRAINING_PROGRAMS
except ImportError:
    # Если config.py не существует, создаем базовую конфигурацию
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    
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

# Файл для хранения данных
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
    
    # Добавляем кнопки управления
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

🎯 Теперь вы можете:
• Видеть все упражнения дня
• Выбирать любое упражнение в любой последовательности
• Возвращаться к пропущенным упражнениям
    """
    update.message.reply_text(welcome_text)
    return CHOOSING_DAY

def start_training_command(update: Update, context: CallbackContext):
    """Команда /train - начало тренировки"""
    return choose_training_day(update, context)

def choose_training_day(update: Update, context: CallbackContext):
    """Выбор дня тренировки"""
    keyboard = [
        ["День А", "День Б"],
        ["/cancel"]
    ]
    reply_markup = ReplyKeyboardMarkup(
        keyboard, 
        one_time_keyboard=True,
        resize_keyboard=True
    )
    
    # Показываем описание программ
    programs_info = "📋 <b>Программы тренировок:</b>\n\n"
    
    for day, program in TRAINING_PROGRAMS.items():
        programs_info += f"<b>{day}</b>\n"
        programs_info += f"{program['description']}\n"
        programs_info += f"<i>Упражнений: {len(program['exercises'])}</i>\n\n"
    
    programs_info += "Выберите день тренировки:"
    
    update.message.reply_text(
        programs_info,
        parse_mode='HTML',
        reply_markup=reply_markup
    )
    return CHOOSING_DAY

def show_exercise_list(update: Update, context: CallbackContext):
    """Показывает список упражнений для выбранного дня"""
    if update.message:
        day = update.message.text
    else:
        # Если вызвано из callback, берем день из context
        day = context.user_data.get('current_day')
    
    user_id = str(update.effective_user.id)
    
    if day not in TRAINING_PROGRAMS:
        update.message.reply_text(
            "❌ Пожалуйста, выберите день из предложенных вариантов",
            reply_markup=ReplyKeyboardRemove()
        )
        return choose_training_day(update, context)
    
    # Загружаем данные
    user_data = load_user_data()
    
    # Инициализируем данные пользователя
    if user_id not in user_data:
        user_data[user_id] = {
            'username': update.effective_user.first_name,
            'history': []
        }
    
    # Сохраняем текущую сессию
    context.user_data['current_day'] = day
    user_data[user_id]['current_session'] = {
        'day': day,
        'exercises': [],
        'start_time': datetime.now().isoformat()
    }
    
    save_user_data(user_data)
    
    # Показываем полный список упражнений
    program = TRAINING_PROGRAMS[day]
    exercises = program['exercises']
    
    exercises_list = "📝 <b>Полный список упражнений:</b>\n\n"
    for i, exercise in enumerate(exercises, 1):
        exercises_list += f"{i}. {exercise}\n"
    
    exercises_list += f"\nВсего упражнений: {len(exercises)}\n\n"
    exercises_list += "👇 Выберите упражнение для ввода результатов:"
    
    # Создаем клавиатуру с упражнениями
    completed_exercises = user_data[user_id]['current_session'].get('completed_exercises', [])
    reply_markup = get_exercise_keyboard(day, completed_exercises)
    
    if update.message:
        update.message.reply_text(
            exercises_list,
            parse_mode='HTML',
            reply_markup=ReplyKeyboardRemove()
        )
        
        update.message.reply_text(
            "🎯 <b>Выберите упражнение:</b>",
            parse_mode='HTML',
            reply_markup=reply_markup
        )
    else:
        update.callback_query.edit_message_text(
            "🎯 <b>Выберите упражнение:</b>",
            parse_mode='HTML',
            reply_markup=reply_markup
        )
    
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
        # Извлекаем индекс упражнения
        exercise_index = int(data.split("_")[1])
        context.user_data['current_exercise'] = exercise_index
        
        day = context.user_data.get('current_day')
        exercises = TRAINING_PROGRAMS[day]['exercises']
        exercise_name = exercises[exercise_index]
        
        # Запрашиваем ввод данных
        query.edit_message_text(
            f"💪 <b>Упражнение:</b> {exercise_name}\n\n"
            f"Введите вес и количество повторений:\n"
            f"<code>вес повторения</code>\n"
            f"Пример: <code>60 10</code>\n\n"
            f"Или нажмите /skip чтобы пропустить",
            parse_mode='HTML'
        )
        
        return ENTERING_EXERCISE_DATA

def handle_exercise_input(update: Update, context: CallbackContext):
    """Обработка ввода данных упражнения"""
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()
    
    # Загружаем данные
    user_data = load_user_data()
    
    if user_id not in user_data or 'current_session' not in user_data[user_id]:
        update.message.reply_text(
            "❌ Сессия тренировки не найдена. Начните заново: /train"
        )
        return ConversationHandler.END
    
    current_session = user_data[user_id]['current_session']
    day = current_session['day']
    exercise_index = context.user_data.get('current_exercise')
    exercises_list = TRAINING_PROGRAMS[day]['exercises']
    exercise_name = exercises_list[exercise_index]
    
    # Парсим ввод
    try:
        parts = text.split()
        if len(parts) != 2:
            raise ValueError("Нужно ввести два числа")
        
        weight = float(parts[0])
        reps = int(parts[1])
        
        if weight <= 0 or reps <= 0:
            raise ValueError("Числа должны быть положительными")
            
    except ValueError as e:
        update.message.reply_text(
            f"❌ Неверный формат: {e}\n\n"
            f"Введите в формате: <code>вес повторения</code>\n"
            f"Пример: <code>60 10</code> или <code>32.5 8</code>",
            parse_mode='HTML'
        )
        return ENTERING_EXERCISE_DATA
    
    # Сохраняем результат текущего упражнения
    exercise_data = {
        'name': exercise_name,
        'weight': weight,
        'reps': reps,
        'timestamp': datetime.now().isoformat()
    }
    
    # Обновляем или добавляем упражнение
    existing_index = None
    for i, ex in enumerate(current_session['exercises']):
        if ex['name'] == exercise_name:
            existing_index = i
            break
    
    if existing_index is not None:
        current_session['exercises'][existing_index] = exercise_data
    else:
        current_session['exercises'].append(exercise_data)
    
    # Обновляем список завершенных упражнений
    if 'completed_exercises' not in current_session:
        current_session['completed_exercises'] = []
    
    if exercise_index not in current_session['completed_exercises']:
        current_session['completed_exercises'].append(exercise_index)
    
    save_user_data(user_data)
    
    # Показываем обновленный список упражнений
    update.message.reply_text(
        f"✅ Сохранено: {exercise_name}\n"
        f"Результат: {weight}кг × {reps}повт.\n\n"
        f"Выберите следующее упражнение:"
    )
    
    return show_exercise_list_after_input(update, context)

def skip_exercise(update: Update, context: CallbackContext):
    """Пропуск упражнения"""
    user_id = str(update.effective_user.id)
    
    # Загружаем данные
    user_data = load_user_data()
    
    if user_id not in user_data or 'current_session' not in user_data[user_id]:
        update.message.reply_text(
            "❌ Сессия тренировки не найдена. Начните заново: /train"
        )
        return ConversationHandler.END
    
    current_session = user_data[user_id]['current_session']
    day = current_session['day']
    exercise_index = context.user_data.get('current_exercise')
    exercises_list = TRAINING_PROGRAMS[day]['exercises']
    exercise_name = exercises_list[exercise_index]
    
    update.message.reply_text(
        f"⏭️ Упражнение пропущено: {exercise_name}\n\n"
        f"Вы можете вернуться к нему позже."
    )
    
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
    
    update.message.reply_text(
        "🎯 <b>Выберите упражнение:</b>",
        parse_mode='HTML',
        reply_markup=reply_markup
    )
    
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
    
    # Показываем сколько осталось
    total_exercises = len(TRAINING_PROGRAMS[day]['exercises'])
    completed_count = len(current_session['exercises'])
    progress_text += f"\n✅ Выполнено: {completed_count}/{total_exercises}"
    
    if update.callback_query:
        update.callback_query.message.reply_text(progress_text, parse_mode='HTML')
        
        # Возвращаем к выбору упражнений
        completed_exercises = current_session.get('completed_exercises', [])
        reply_markup = get_exercise_keyboard(day, completed_exercises)
        update.callback_query.message.reply_text(
            "🎯 <b>Выберите упражнение:</b>",
            parse_mode='HTML',
            reply_markup=reply_markup
        )
    
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
    
    # Проверяем, есть ли выполненные упражнения
    if not current_session['exercises']:
        if update.callback_query:
            update.callback_query.message.reply_text(
                "❌ Вы не выполнили ни одного упражнения. Тренировка отменена."
            )
        # Удаляем пустую сессию
        del user_data[user_id]['current_session']
        save_user_data(user_data)
        return ConversationHandler.END
    
    # Добавляем в историю
    user_data[user_id]['history'].append(current_session)
    
    # Очищаем текущую сессию
    del user_data[user_id]['current_session']
    
    save_user_data(user_data)
    
    # Формируем сводку
    summary = "🎉 Тренировка завершена! 🎉\n\n<b>Ваши результаты:</b>\n"
    
    for i, exercise in enumerate(current_session['exercises'], 1):
        summary += f"{i}. {exercise['name']}: {exercise['weight']}кг × {exercise['reps']}повт.\n"
    
    total_exercises = len(TRAINING_PROGRAMS[day]['exercises'])
    completed_count = len(current_session['exercises'])
    summary += f"\n💪 Выполнено: {completed_count}/{total_exercises} упражнений"
    summary += f"\n\nОтличная работа! Следующая тренировка через 1-2 дня."
    
    keyboard = [
        ["/train", "/progress"],
        ["/stats", "/help"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    if update.callback_query:
        update.callback_query.message.reply_text(
            summary,
            parse_mode='HTML',
            reply_markup=reply_markup
        )
    else:
        update.message.reply_text(
            summary,
            parse_mode='HTML',
            reply_markup=reply_markup
        )
    
    return ConversationHandler.END

def view_progress(update: Update, context: CallbackContext):
    """Команда /progress - просмотр истории тренировок"""
    user_id = str(update.effective_user.id)
    user_data = load_user_data()
    
    if user_id not in user_data or not user_data[user_id].get('history'):
        update.message.reply_text(
            "📊 У вас пока нет записей о тренировках.\n"
            "Начните первую тренировку: /train"
        )
        return
    
    history = user_data[user_id]['history']
    
    response = "📊 <b>История ваших тренировок:</b>\n\n"
    
    # Показываем последние 5 тренировок
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
        update.message.reply_text(
            "📈 У вас пока нет данных для статистики.\n"
            "Начните первую тренировку: /train"
        )
        return
    
    history = user_data[user_id]['history']
    
    stats_text = "📈 <b>Ваша статистика:</b>\n\n"
    stats_text += f"Всего тренировок: <b>{len(history)}</b>\n"
    
    # Считаем тренировки по дням
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

<b>Новые возможности:</b>
• 📋 <b>Просмотр всех упражнений</b> перед началом тренировки
• 🎯 <b>Свободный порядок</b> - выбирайте упражнения в любой последовательности
• ⏭️ <b>Пропуск упражнений</b> - используйте /skip чтобы пропустить упражнение
• 🔄 <b>Возврат к упражнениям</b> - можно вернуться к пропущенным упражнениям

<b>Как работать с ботом:</b>
1. Нажмите /train
2. Выберите день тренировки
3. Просмотрите полный список упражнений
4. Выбирайте упражнения в любом порядке
5. Вводите данные в формате: <code>вес повторения</code>
6. Завершите тренировку когда закончите

<b>О программе тренировок:</b>
• <b>День А</b>: Горизонтальные жимы + вертикальные тяги
• <b>День Б</b>: Вертикальные жимы + горизонтальные тяги

💡 <b>Рекомендация:</b> Чередуйте дни по схеме:
Неделя 1: А-Б-А, Неделя 2: Б-А-Б
    """
    update.message.reply_text(help_text, parse_mode='HTML')

def cancel(update: Update, context: CallbackContext):
    """Отмена текущей операции"""
    user_id = str(update.effective_user.id)
    user_data = load_user_data()
    
    # Очищаем текущую сессию если есть
    if user_id in user_data and 'current_session' in user_data[user_id]:
        del user_data[user_id]['current_session']
        save_user_data(user_data)
    
    update.message.reply_text(
        "❌ Тренировка отменена.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

def error_handler(update: Update, context: CallbackContext):
    """Обработка ошибок"""
    logger.error(f"Ошибка: {context.error}", exc_info=context.error)
    
    if update and update.effective_message:
        update.effective_message.reply_text(
            "❌ Произошла ошибка. Попробуйте еще раз или начните заново: /start"
        )

  def main():
    """Основная функция запуска бота"""
    # Проверяем токен
    if not BOT_TOKEN:
        print("❌ Ошибка: BOT_TOKEN не найден!")
        print("Установите переменную BOT_TOKEN в настройках Railway")
        return
    
    # Создаем updater и dispatcher
    updater = Updater(BOT_TOKEN, use_context=True)
    dispatcher = updater.dispatcher
    
    # [остальной код обработчиков без изменений]
    
    # Запускаем бота
    print("🤖 Бот запускается на Railway...")
    print("⏹️ Для остановки используйте панель Railway")
    
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()