FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY nhl_mvp.py backtest.py improved_model.py independent_model.py run_pipeline.py ./
CMD ["python", "-u", "run_pipeline.py"]
