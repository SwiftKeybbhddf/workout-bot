import logging
import json
import os
import signal
import sys
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,  # Изменено: Application вместо Updater
    CommandHandler, 
    MessageHandler, 
    filters,  # Изменено: filters вместо Filters
    ContextTypes,  # Изменено: ContextTypes вместо CallbackContext
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
application = None  # Изменено: application вместо updater

def signal_handler(signum, frame):
    """Обработчик сигналов для graceful shutdown"""
    print(f"📞 Получен сигнал {signum}, завершаем работу бота...")
    
    global application
    if application is not None:
        print("🛑 Останавливаем application...")
        application.stop()
        print("✅ Application остановлен")
    
    print("👋 Бот завершил работу")
    sys.exit(0)

# Регистрируем обработчики сигналов
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.environ.get('BOT_TOKEN')

if not BOT_TOKEN:
    print("❌ ОШИБКА: BOT_TOKEN не найден!")
    exit(1)

print("✅ BOT_TOKEN найден, запускаем бота...")

# ... остальной код остается таким же до функций ...

# ========== ФУНКЦИИ ТАЙМЕРА ==========
def timer_callback(context: ContextTypes.DEFAULT_TYPE):  # Изменено: ContextTypes
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

def start_timer_progress(context: ContextTypes.DEFAULT_TYPE):  # Изменено: ContextTypes
    """Функция для обновления прогресса таймера"""
    job = context.job
    chat_id = job.context['chat_id']
    timer_name = job.context['timer_name']
    remaining = job.context['remaining']
    message_id = job.context.get('message_id')
    
    if remaining <= 0:
        return
    
    try:
        if message_id:
            context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"⏰ Таймер {timer_name}\nОсталось: {remaining} сек."
            )
        else:
            message = context.bot.send_message(
                chat_id=chat_id,
                text=f"⏰ Таймер {timer_name}\nОсталось: {remaining} сек."
            )
            job.context['message_id'] = message.message_id
        
        job.context['remaining'] = remaining - 1
        
    except Exception as e:
        print(f"❌ Ошибка обновления таймера: {e}")

def set_timer(update: Update, context: ContextTypes.DEFAULT_TYPE, duration: int, timer_name: str):  # Изменено: ContextTypes
    """Устанавливает таймер через job queue"""
    chat_id = update.effective_message.chat_id
    
    timer_job_context = {'chat_id': chat_id, 'timer_name': timer_name}
    progress_job_context = {'chat_id': chat_id, 'timer_name': timer_name, 'remaining': duration}
    
    # Запускаем прогресс таймера
    progress_job = context.job_queue.run_repeating(
        start_timer_progress,
        interval=1,
        first=0,
        context=progress_job_context,
        name=f"timer_progress_{chat_id}"
    )
    
    # Запускаем основной таймер
    context.job_queue.run_once(
        timer_callback,
        duration,
        context=timer_job_context,
        name=f"timer_end_{chat_id}"
    )
    
    # Останавливаем прогресс таймера после завершения
    context.job_queue.run_once(
        lambda ctx: progress_job.schedule_removal(),
        duration,
        context={},
        name=f"timer_cleanup_{chat_id}"
    )
    
    print(f"✅ Таймер {timer_name} установлен на {duration} секунд для чата {chat_id}")
    return f"⏰ Таймер {timer_name} установлен на {duration} секунд"

# ... остальной код остается прежним до main() ...

# ========== ЗАПУСК БОТА ==========
async def main():
    """Основная функция запуска бота"""
    global application
    
    print("🤖 Бот запускается...")
    
    if not BOT_TOKEN:
        print("❌ Не могу запустить бота без BOT_TOKEN")
        return
    
    try:
        # Создаем Application вместо Updater
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Обработчик диалога тренировки
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler('train', start_training_command),
                CommandHandler('weight', weight_command)
            ],
            states={
                CHOOSING_DAY: [MessageHandler(filters.Regex('^(День А|День Б)$'), show_exercise_list)],  # Изменено: filters.Regex
                CHOOSING_EXERCISE: [
                    CallbackQueryHandler(handle_exercise_selection, pattern='^(ex_|progress|finish|reminders|stats|timer_|back_to_exercises)'),
                    CallbackQueryHandler(show_exercise_statistics, pattern='^(stat_)')
                ],
                ENTERING_EXERCISE_DATA: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_exercise_input),  # Изменено: filters.TEXT и filters.COMMAND
                    CommandHandler('skip', skip_exercise),
                    CallbackQueryHandler(handle_exercise_selection, pattern='^(progress|finish|reminders|stats|timer_|back_to_exercises)')
                ],
                WEIGHING: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_weight_input),  # Изменено: filters.TEXT и filters.COMMAND
                    CommandHandler('skip', skip_weight)
                ]
            },
            fallbacks=[CommandHandler('cancel', cancel)],
        )
        
        # Регистрируем обработчики
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("progress", view_progress))
        application.add_handler(CommandHandler("stats", view_stats))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("cancel", cancel))
        application.add_handler(conv_handler)
        application.add_error_handler(error_handler)
        
        print("✅ Бот успешно запущен и готов к работе!")
        
        # Запускаем бота
        await application.run_polling()
        
    except Exception as e:
        print(f"❌ Ошибка при запуске бота: {e}")
        sys.exit(1)

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
