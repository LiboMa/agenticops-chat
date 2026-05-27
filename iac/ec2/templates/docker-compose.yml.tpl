services:
  agenticops:
    image: ${image_uri}
    env_file: /opt/agenticops/.env
    ports:
      - "8000:8000"
    volumes:
      - /opt/agenticops/data:/app/data
    restart: always
    logging:
      driver: awslogs
      options:
        awslogs-region: ${region}
        awslogs-group: /${project_name}
        awslogs-stream-prefix: app
        awslogs-create-group: "true"
