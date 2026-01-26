"""채용공고 크롤러 어댑터"""

from adapters.job_crawlers.base_crawler import BaseJobCrawler, CrawlerConfig
from adapters.job_crawlers.saramin_crawler import SaraminCrawler
from adapters.job_crawlers.jobkorea_crawler import JobKoreaCrawler
from adapters.job_crawlers.wanted_crawler import WantedCrawler

__all__ = [
    "BaseJobCrawler",
    "CrawlerConfig",
    "SaraminCrawler",
    "JobKoreaCrawler",
    "WantedCrawler",
]
