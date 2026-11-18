ARG BUILD_FROM
FROM $BUILD_FROM
COPY integrations /integrations
RUN apk add --no-cache mosquitto-clients
COPY run.sh telemetry.sh telemetry.j2 /
RUN chmod a+x /run.sh
CMD [ "/run.sh" ]
