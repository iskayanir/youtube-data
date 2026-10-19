import azure.functions as func
import datetime
import json
import logging
from main_yt import main
import os

app = func.FunctionApp()

@app.timer_trigger(schedule="0 */1 * * * *", arg_name="myTimer", run_on_startup=False,
              use_monitor=False) 
def insert_data_yt_to_forcast(myTimer: func.TimerRequest) -> None:
    main()
    if myTimer.past_due:
        logging.info('The timer is past due!')
    logging.info('Python timer trigger function executed.')