FROM python:3.12-alpine
WORKDIR /app
COPY health.py /app/health.py
USER 65532:65532
EXPOSE 8766
CMD ["python", "/app/health.py"]
