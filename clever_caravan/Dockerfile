ARG BUILD_FROM
FROM $BUILD_FROM
COPY integrations /integrations
COPY run.sh /
RUN chmod a+x /run.sh
CMD [ "/run.sh" ]
