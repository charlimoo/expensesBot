
class OpenAIHelper:
    """
    ChatGPT helper class.
    """

    def __init__(self, config: dict, plugin_manager: PluginManager):
        """
        Initializes the OpenAI helper class with the given configuration.
        :param config: A dictionary containing the GPT configuration
        :param plugin_manager: The plugin manager
        """
        http_client = httpx.AsyncClient(proxies=config['proxy']) if 'proxy' in config else None
        self.client = openai.AsyncOpenAI(api_key=config['api_key'], http_client=http_client)
        self.config = config
        self.plugin_manager = plugin_manager
        self.conversations: dict[int: list] = {}  # {chat_id: history}
        self.conversations_vision: dict[int: bool] = {}  # {chat_id: is_vision}
        self.last_updated: dict[int: datetime] = {}  # {chat_id: last_update_timestamp}

    def get_conversation_stats(self, chat_id: int) -> tuple[int, int]:
        """
        Gets the number of messages and tokens used in the conversation.
        :param chat_id: The chat ID
        :return: A tuple containing the number of messages and tokens used
        """
        if chat_id not in self.conversations:
            self.reset_chat_history(chat_id)
        return len(self.conversations[chat_id]), self.__count_tokens(self.conversations[chat_id])

    async def get_chat_response(self, chat_id: int, query: str) -> tuple[str, str]:
        """
        Gets a full response from the GPT model.
        :param chat_id: The chat ID
        :param query: The query to send to the model
        :return: The answer from the model and the number of tokens used
        """
        plugins_used = ()
        response = await self.__common_get_chat_response(chat_id, query)
        if self.config['enable_functions'] and not self.conversations_vision[chat_id]:
            response, plugins_used = await self.__handle_function_call(chat_id, response)
            if is_direct_result(response):
                return response, '0'

        answer = ''

        if len(response.choices) > 1 and self.config['n_choices'] > 1:
            for index, choice in enumerate(response.choices):
                content = choice.message.content.strip()
                if index == 0:
                    self.__add_to_history(chat_id, role="assistant", content=content)
                answer += f'{index + 1}\u20e3\n'
                answer += content
                answer += '\n\n'
        else:
            answer = response.choices[0].message.content.strip()
            self.__add_to_history(chat_id, role="assistant", content=answer)

        bot_language = self.config['bot_language']
        show_plugins_used = len(plugins_used) > 0 and self.config['show_plugins_used']
        plugin_names = tuple(self.plugin_manager.get_plugin_source_name(plugin) for plugin in plugins_used)
        if self.config['show_usage']:
            answer += "\n\n---\n" \
                      f"💰 {str(response.usage.total_tokens)} {localized_text('stats_tokens', bot_language)}" \
                      f" ({str(response.usage.prompt_tokens)} {localized_text('prompt', bot_language)}," \
                      f" {str(response.usage.completion_tokens)} {localized_text('completion', bot_language)})"
            if show_plugins_used:
                answer += f"\n🔌 {', '.join(plugin_names)}"
        elif show_plugins_used:
            answer += f"\n\n---\n🔌 {', '.join(plugin_names)}"

        return answer, response.usage.total_tokens

    async def get_chat_response_stream(self, chat_id: int, query: str):
        """
        Stream response from the GPT model.
        :param chat_id: The chat ID
        :param query: The query to send to the model
        :return: The answer from the model and the number of tokens used, or 'not_finished'
        """
        plugins_used = ()
        response = await self.__common_get_chat_response(chat_id, query, stream=True)
        if self.config['enable_functions'] and not self.conversations_vision[chat_id]:
            response, plugins_used = await self.__handle_function_call(chat_id, response, stream=True)
            if is_direct_result(response):
                yield response, '0'
                return

        answer = ''
        async for chunk in response:
            if len(chunk.choices) == 0:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                answer += delta.content
                yield answer, 'not_finished'
        answer = answer.strip()
        self.__add_to_history(chat_id, role="assistant", content=answer)
        tokens_used = str(self.__count_tokens(self.conversations[chat_id]))

        show_plugins_used = len(plugins_used) > 0 and self.config['show_plugins_used']
        plugin_names = tuple(self.plugin_manager.get_plugin_source_name(plugin) for plugin in plugins_used)
        if self.config['show_usage']:
            answer += f"\n\n---\n💰 {tokens_used} {localized_text('stats_tokens', self.config['bot_language'])}"
            if show_plugins_used:
                answer += f"\n🔌 {', '.join(plugin_names)}"
        elif show_plugins_used:
            answer += f"\n\n---\n🔌 {', '.join(plugin_names)}"

        yield answer, tokens_used

    @retry(
        reraise=True,
        retry=retry_if_exception_type(openai.RateLimitError),
        wait=wait_fixed(20),
        stop=stop_after_attempt(3)
    )
    async def __common_get_chat_response(self, chat_id: int, query: str, stream=False):
        """
        Request a response from the GPT model.
        :param chat_id: The chat ID
        :param query: The query to send to the model
        :return: The answer from the model and the number of tokens used
        """
        bot_language = self.config['bot_language']
        try:
            if chat_id not in self.conversations or self.__max_age_reached(chat_id):
                self.reset_chat_history(chat_id)

            self.last_updated[chat_id] = datetime.datetime.now()

            self.__add_to_history(chat_id, role="user", content=query)

            # Summarize the chat history if it's too long to avoid excessive token usage
            token_count = self.__count_tokens(self.conversations[chat_id])
            exceeded_max_tokens = token_count + self.config['max_tokens'] > self.__max_model_tokens()
            exceeded_max_history_size = len(self.conversations[chat_id]) > self.config['max_history_size']

            if exceeded_max_tokens or exceeded_max_history_size:
                logging.info(f'Chat history for chat ID {chat_id} is too long. Summarising...')
                try:
                    summary = await self.__summarise(self.conversations[chat_id][:-1])
                    logging.debug(f'Summary: {summary}')
                    self.reset_chat_history(chat_id, self.conversations[chat_id][0]['content'])
                    self.__add_to_history(chat_id, role="assistant", content=summary)
                    self.__add_to_history(chat_id, role="user", content=query)
                except Exception as e:
                    logging.warning(f'Error while summarising chat history: {str(e)}. Popping elements instead...')
                    self.conversations[chat_id] = self.conversations[chat_id][-self.config['max_history_size']:]

            common_args = {
                'model': self.config['model'] if not self.conversations_vision[chat_id] else self.config['vision_model'],
                'messages': self.conversations[chat_id],
                'temperature': self.config['temperature'],
                'n': self.config['n_choices'],
                'max_tokens': self.config['max_tokens'],
                'presence_penalty': self.config['presence_penalty'],
                'frequency_penalty': self.config['frequency_penalty'],
                'stream': stream
            }

            if self.config['enable_functions'] and not self.conversations_vision[chat_id]:
                functions = self.plugin_manager.get_functions_specs()
                if len(functions) > 0:
                    common_args['functions'] = self.plugin_manager.get_functions_specs()
                    common_args['function_call'] = 'auto'
            return await self.client.chat.completions.create(**common_args)

        except openai.RateLimitError as e:
            raise e

        except openai.BadRequestError as e:
            raise Exception(f"⚠️ _{localized_text('openai_invalid', bot_language)}._ ⚠️\n{str(e)}") from e

        except Exception as e:
            raise Exception(f"⚠️ _{localized_text('error', bot_language)}._ ⚠️\n{str(e)}") from e

    async def __handle_function_call(self, chat_id, response, stream=False, times=0, plugins_used=()):
        function_name = ''
        arguments = ''
        if stream:
            async for item in response:
                if len(item.choices) > 0:
                    first_choice = item.choices[0]
                    if first_choice.delta and first_choice.delta.function_call:
                        if first_choice.delta.function_call.name:
                            function_name += first_choice.delta.function_call.name
                        if first_choice.delta.function_call.arguments:
                            arguments += first_choice.delta.function_call.arguments
                    elif first_choice.finish_reason and first_choice.finish_reason == 'function_call':
                        break
                    else:
                        return response, plugins_used
                else:
                    return response, plugins_used
        else:
            if len(response.choices) > 0:
                first_choice = response.choices[0]
                if first_choice.message.function_call:
                    if first_choice.message.function_call.name:
                        function_name += first_choice.message.function_call.name
                    if first_choice.message.function_call.arguments:
                        arguments += first_choice.message.function_call.arguments
                else:
                    return response, plugins_used
            else:
                return response, plugins_used

        logging.info(f'Calling function {function_name} with arguments {arguments}')
        function_response = await self.plugin_manager.call_function(function_name, self, arguments)

        if function_name not in plugins_used:
            plugins_used += (function_name,)

        if is_direct_result(function_response):
            self.__add_function_call_to_history(chat_id=chat_id, function_name=function_name,
                                                content=json.dumps({'result': 'Done, the content has been sent'
                                                                              'to the user.'}))
            return function_response, plugins_used

        self.__add_function_call_to_history(chat_id=chat_id, function_name=function_name, content=function_response)
        response = await self.client.chat.completions.create(
            model=self.config['model'],
            messages=self.conversations[chat_id],
            functions=self.plugin_manager.get_functions_specs(),
            function_call='auto' if times < self.config['functions_max_consecutive_calls'] else 'none',
            stream=stream
        )
        return await self.__handle_function_call(chat_id, response, stream, times + 1, plugins_used)
