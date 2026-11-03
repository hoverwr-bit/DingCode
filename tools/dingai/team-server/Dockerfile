FROM python:3.12-slim
WORKDIR /app
COPY team-server/dingai_team_server.py team-server/dingai_team_server.py
COPY core core
WORKDIR /app/team-server
ENV DINGAI_TEAM_HOST=0.0.0.0
ENV DINGAI_TEAM_PORT=8050
ENV DINGAI_TEAM_ROOT=/data
ENV DINGAI_TEAM_REQUIRE_AUTH=1
VOLUME /data
EXPOSE 8050
CMD ["python3", "dingai_team_server.py"]
