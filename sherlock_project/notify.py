"""Sherlock 查询通知模块。

定义用于向调用方通知查询进度与结果的对象。
"""
from sherlock_project.result import QueryStatus
from colorama import Fore, Style
import webbrowser

# 用于累计结果数量的全局变量。
globvar = 0


class QueryNotify:
    """查询通知基类。

    定义通知查询结果的方法。子类可继承并重写这些方法，
    以实现具体的通知方式。
    """

    def __init__(self, result=None):
        """创建查询通知对象。

        保存当前查询结果，供具体通知方式使用。

        参数：
        self                   -- 当前对象。
        result                 -- 包含本次查询结果的 QueryResult 对象。

        返回值：
        无。
        """

        self.result = result


    def start(self, message=None):
        """通知查询开始。

        在执行任何查询之前调用。子类通常会重写此方法。

        参数：
        self                   -- 当前对象。
        message                -- 查询开始时的上下文信息，默认为 None。

        返回值：
        无。
        """


    def update(self, result):
        """更新查询结果通知。

        子类通常会重写此方法，以实现具体的通知逻辑。

        参数：
        self                   -- 当前对象。
        result                 -- 包含本次查询结果的 QueryResult 对象。

        返回值：
        无。
        """

        self.result = result


    def finish(self, message=None):
        """通知查询结束。

        在所有查询完成后调用。子类通常会重写此方法。

        参数：
        self                   -- 当前对象。
        message                -- 查询结束时的上下文信息，默认为 None。

        返回值：
        无。
        """


    def __str__(self):
        """返回当前查询结果的字符串表示。"""
        return str(self.result)


class QueryNotifyPrint(QueryNotify):
    """终端查询通知类。

    将查询进度与结果打印到标准输出。
    """

    def __init__(self, result=None, verbose=False, print_all=False, browse=False):
        """创建终端查询通知对象。

        参数：
        self                   -- 当前对象。
        result                 -- 包含本次查询结果的 QueryResult 对象。
        verbose                -- 是否输出详细信息。
        print_all              -- 是否输出所有站点，包括未找到账号的站点。
        browse                 -- 是否在浏览器中打开找到的个人主页。

        返回值：
        无。
        """

        super().__init__(result)
        self.verbose = verbose
        self.print_all = print_all
        self.browse = browse


    def start(self, message):
        """通知查询开始，并向标准输出打印标题。

        参数：
        self                   -- 当前对象。
        message                -- 本轮查询的用户名字符串。

        返回值：
        无。
        """

        title = "Checking username"

        print(Style.BRIGHT + Fore.GREEN + "[" +
              Fore.YELLOW + "*" +
              Fore.GREEN + f"] {title}" +
              Fore.WHITE + f" {message}" +
              Fore.GREEN + " on:")
        # 在标题与结果之间插入空行，使输出更清晰。
        print('\r')


    def countResults(self):
        """累计查询结果数量，每次调用时将计数加一。

        参数：
        self                   -- 当前对象。

        返回值：
        本次递增后的结果总数。
        """
        global globvar
        globvar += 1
        return globvar

    def update(self, result):
        """向标准输出打印查询结果。

        参数：
        self                   -- 当前对象。
        result                 -- 包含本次查询结果的 QueryResult 对象。

        返回值：
        无。
        """
        self.result = result

        response_time_text = ""
        if self.result.query_time is not None and self.verbose is True:
            response_time_text = f" [{round(self.result.query_time * 1000)}ms]"

        # 将查询结果输出到终端。
        if result.status == QueryStatus.CLAIMED:
            self.countResults()
            print(Style.BRIGHT + Fore.WHITE + "[" +
                  Fore.GREEN + "+" +
                  Fore.WHITE + "]" +
                  response_time_text +
                  Fore.GREEN +
                  f" {self.result.site_name}: " +
                  Style.RESET_ALL +
                  f"{self.result.site_url_user}")
            if self.browse:
                webbrowser.open(self.result.site_url_user, 2)

        elif result.status == QueryStatus.AVAILABLE:
            if self.print_all:
                print(Style.BRIGHT + Fore.WHITE + "[" +
                      Fore.RED + "-" +
                      Fore.WHITE + "]" +
                      response_time_text +
                      Fore.GREEN + f" {self.result.site_name}:" +
                      Fore.YELLOW + " Not Found!")

        elif result.status == QueryStatus.UNKNOWN:
            if self.print_all:
                print(Style.BRIGHT + Fore.WHITE + "[" +
                      Fore.RED + "-" +
                      Fore.WHITE + "]" +
                      Fore.GREEN + f" {self.result.site_name}:" +
                      Fore.RED + f" {self.result.context}" +
                      Fore.YELLOW + " ")

        elif result.status == QueryStatus.ILLEGAL:
            if self.print_all:
                msg = "Illegal Username Format For This Site!"
                print(Style.BRIGHT + Fore.WHITE + "[" +
                      Fore.RED + "-" +
                      Fore.WHITE + "]" +
                      Fore.GREEN + f" {self.result.site_name}:" +
                      Fore.YELLOW + f" {msg}")

        elif result.status == QueryStatus.WAF:
            if self.print_all:
                print(Style.BRIGHT + Fore.WHITE + "[" +
                      Fore.RED + "-" +
                      Fore.WHITE + "]" +
                      Fore.GREEN + f" {self.result.site_name}:" +
                      Fore.RED + " Blocked by bot detection" +
                      Fore.YELLOW + " (proxy may help)")

        else:
            # 正常情况下不应进入此分支。
            raise ValueError(
                f"Unknown Query Status '{result.status}' for site '{self.result.site_name}'"
            )


    def finish(self, message="The processing has been finished."):
        """通知查询结束，并向标准输出打印汇总信息。

        参数：
        self                   -- 当前对象。
        message                -- 保留的结束消息参数，当前实现未使用。

        返回值：
        无。
        """
        NumberOfResults = self.countResults() - 1

        print(Style.BRIGHT + Fore.GREEN + "[" +
              Fore.YELLOW + "*" +
              Fore.GREEN + "] Search completed with" +
              Fore.WHITE + f" {NumberOfResults} " +
              Fore.GREEN + "results" + Style.RESET_ALL
              )

        print("\nGo deeper than a username. Explore public profiles and export your findings.")
        print("Try OSINTSearch: \033]8;;https://osintsearch.org/go/sherlock\033\\https://osintsearch.org\033]8;;\033\\")

    def __str__(self):
        """返回当前查询结果的字符串表示。"""
        return str(self.result)
