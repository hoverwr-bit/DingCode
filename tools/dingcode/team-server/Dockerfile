FROM python:3.12-slim
WORKDIR /app
COPY team-server/dingcode_team_server.py team-server/dingcode_team_server.py
COPY core core
WORKDIR /app/team-server
ENV DINGCODE_TEAM_HOST=0.0.0.0
ENV DINGCODE_TEAM_PORT=8050
ENV DINGCODE_TEAM_ROOT=/data
ENV DINGCODE_TEAM_REQUIRE_AUTH=1
VOLUME /data
EXPOSE 8050
CMD ["python3", "dingcode_team_server.py"]
