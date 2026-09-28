FROM python:3.10-slim-bookworm

WORKDIR /opt/dsb
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY startup.sh .
COPY app ./app
# Required. The previous image never copied private/, so the container
# could not see the fonts that exist at the repository root.
COPY private ./private

ENV APP_BASE_DIR=/opt/dsb
ENV HOST=0.0.0.0
EXPOSE 8080

CMD ["sh", "/opt/dsb/startup.sh"]
