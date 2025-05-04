import logging

class Logger:
    """
    Represents a logger object that is used to log messages. This class implements a Singleton pattern, call
    get_logger() to get the logger object after instantiation.
    """

    def __init__(self, logger_name: str, log_level: int, log_format: str, log_file: str, log_mode: str):
        """
        Constructor for Logger class.
        :param logger_name: the name of the logger.
        :param log_level: the log level.
        :param log_format: the log format.
        :param log_file: the log file path.
        """
        # Create a file handler for logging to a file
        self.file_handler = logging.FileHandler(log_file, mode=log_mode)
        self.file_handler.setLevel(log_level)  # Log level for file, can be adjusted as needed
        self.file_handler.setFormatter(logging.Formatter(log_format))
        # Create a stream handler for logging to the console
        self.stream_handler = logging.StreamHandler()
        self.stream_handler.setLevel(log_level)  # Log level for console, can be adjusted as needed
        self.stream_handler.setFormatter(logging.Formatter(log_format))
        # Add both handlers to the root logger
        self.logger = logging.getLogger(logger_name)
        self.logger.addHandler(self.file_handler)
        self.logger.addHandler(self.stream_handler)
        self.logger.setLevel(log_level)

    def get_logger(self) -> logging.Logger:
        """
        Returns the logger object.
        :return: the logger object.
        """
        return self.logger