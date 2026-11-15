FROM python:3.9-slim
LABEL maintainer="Your Name <you@example.com>"

# Show print/log output immediately in `docker compose logs`
ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Files copied from Windows arrive marked executable, and nose
# skips executable files, so clear that flag.
RUN chmod -x *.py

EXPOSE 5000
ENTRYPOINT ["python"]
CMD ["flask_brevets.py"]
