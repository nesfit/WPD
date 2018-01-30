import logging
import asyncio

# third party imports
import dependency_injector.providers as providers
import dependency_injector.containers as containers
from selenium.webdriver import DesiredCapabilities

# local imports
import lemmiwinks.meta_singleton as singleton
from . import client
from . import exception
from .container import InstanceStatus


class ClientFactory:
    def __init__(self, cls, **kwargs):
        self.__cls = cls
        self.__kwargs = kwargs

    @property
    def client(self):
        return providers.Factory(self.__cls, **self.__kwargs)

    @property
    def singleton_client(self):
        return providers.ThreadSafeSingleton(self.__cls, **self.__kwargs)


class ClientFactoryProvider(containers.DeclarativeContainer):
    aio_factory = ClientFactory(client.AIOClient)

    selenium_factory = ClientFactory(client.SeleniumClient)

    phantomjs_factory = ClientFactory(client.SeleniumClient,
                                      browser_info=DesiredCapabilities.PHANTOMJS)

    firefox_factory = ClientFactory(client.SeleniumClient,
                                    browser_info=DesiredCapabilities.FIREFOX)

    chrome_factory = ClientFactory(client.SeleniumClient,
                                   browser_info=DesiredCapabilities.CHROME)


class ClientPool(metaclass=singleton.ThreadSafeSingleton):
    def __init__(self, factory, max_pool=10, **kwargs):
        self.__logger = logging.getLogger(__name__+"."+__class__.__name__)
        self._max_pool = max_pool
        self._assign_dict = dict()

        self._factory = factory
        self._kwargs = kwargs

        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max_pool)

    def __del__(self):
        for key in self._assign_dict:
            del key

    async def acquire(self):
        await self._semaphore.acquire()
        with await self._lock:
            instance = self.__acquire_instance()

        return instance

    def __acquire_instance(self):
        if self.__is_instance_awaliable():
            instance = self.__get_awaliable_instance()
            self.__update_instance_state_to(instance, InstanceStatus.RESERVED)
        # create new a instance and assign it to the dictionary
        else:
            instance = self._factory.client(**self._kwargs)
            self.__update_instance_state_to(instance, InstanceStatus.RESERVED)

        return instance

    def __is_instance_awaliable(self):
        return InstanceStatus.AWALIABLE in self._assign_dict.values()

    def __get_awaliable_instance(self):
        try:
            instance = (inst for inst, status in self._assign_dict.items()
                        if status is InstanceStatus.AWALIABLE).__next__()
        except Exception as e:
            self.__logger.critical(e)
            raise exception.PoolError(e)
        else:
            return instance

    def __update_instance_state_to(self, instance, state: InstanceStatus):
        self._assign_dict.update({instance: state})

    def release(self, instance):
        self.__update_instance_state_to(instance, InstanceStatus.AWALIABLE)
        self._semaphore.release()