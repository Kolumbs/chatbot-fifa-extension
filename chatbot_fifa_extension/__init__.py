"""Package allows to extend a chatbot with FIFA World Cup results prediction game"""
from zoozl.chat.api import Interface, Message


class FIFAGame(Interface):
    """Allows to make predictions for World Cup results"""
    aliases = {"play fifa", "play world cup"}

    def consume(self, package):
        package.callback("Work in progress. Stay tuned!")
