# program:    PopPyramid_US_1970-2017_2020-01-15,r
# task:       Create Population Pyramids
# version:    v3 - fixed issue with missing data
# project:    Population Pyramid publication to ICPSR
# author:     Nathanael Rosenheim \ Oct 31, 2019

# *******-*********-*********-*********-*********-*********-*********/
#  Install Packages                                                 */
# *******-*********-*********-*********-*********-*********-*********/
# This program requires ggplot2 and ggpubr. 
# ggplot2 is a powerful data visualization tool - ggplot2 version 3.2.1
# ggpubr makes it easy to combine multiple ggplots - ggpubr version 0.2.4

# To install packages in RStudio 
## 1. Click on the Packages tab in the bottom-right section 
## 2. Click on install. 
## 3. Type the name of the packages to install

# *******-*********-*********-*********-*********-*********-*********/
#  Load Packages                                                    */
# *******-*********-*********-*********-*********-*********-*********/

library(ggplot2)
library(ggpubr)

# *******-*********-*********-*********-*********-*********-*********/
#  Obtain Age and Sex Data                                          */
# *******-*********-*********-*********-*********-*********-*********/
# Formatted age and sex by 5 year cohorot data for population pyarmids
# Source: Surveillance, Epidemiology, and End Results (SEER) 
#           Program Populations (1969-2017) (www.seer.cancer.gov/popdata), 
#           National Cancer Institute, DCCPS, Surveillance Research Program, 
#           released December 2018.


df <- read.csv("PopPyramid_US_1970-2017_2020-01-15.csv",
               header= TRUE)

# *******-*********-*********-*********-*********-*********-*********/
#  Function That Will Generate Pop Pyramid for any state/county     */
# *******-*********-*********-*********-*********-*********-*********/
# This function uses GGPLOT to make two histograms
# One histogram for the Male Population and 
# one histogram for the Female Popopulation
# The command coord_flip() roates the histograms

pop_pyramid_year <- function(year,fips){
  dfyear <- df[(df$year == year) & (df$fips == fips), ] 
  dfyear$agestr <- factor(dfyear$agestr, levels = dfyear$agestr, labels = dfyear$agestr)
  
  # Save geography name for title
  geoname <- as.character(dfyear[1,4])
  st <- as.character(dfyear[1,5])
  
  pop_pyramid <- ggplot(dfyear, aes(x = agestr, y = prctpop, fill = gender)) + 
    geom_bar(data = subset(dfyear,gender == "Male"), stat = "identity", 
             position = position_dodge(preserve = "single")) +
    geom_bar(data = subset(dfyear,gender == "Female"), stat = "identity", 
             position = position_dodge(preserve = "single")) +
    coord_flip() +
    scale_y_continuous(breaks = seq(-20, 20, 2), 
                       labels = paste0(as.character(c(seq(20, 0, -2), seq(2, 20, 2))), "%")) + 
    scale_fill_brewer(palette = "Set1") + 
    theme_bw() +
    xlab("Age") + ylab("Population (%)") +
    ggtitle(paste0(geoname,", ",st,", ",year)) +
    guides(fill=guide_legend(title=NULL, reverse = TRUE)) +
    theme(legend.position = c(0.2,0.95), 
          legend.direction = "horizontal", 
          legend.background = element_blank())
  
  return(pop_pyramid)
}

# *******-*********-*********-*********-*********-*********-*********/
#  Function that combines 6 population pyramids into one figure     */
# *******-*********-*********-*********-*********-*********-*********/

# This function combines 6 population pyramids into 1 figure
pop_pyramid_6years <- function(fips){
  # The following set of code combines 6 pyramids into one image
  figure <- ggarrange(pop_pyramid_year(1970,fips),
                      pop_pyramid_year(1980,fips),
                      pop_pyramid_year(1990,fips),
                      pop_pyramid_year(2000,fips),
                      pop_pyramid_year(2010,fips),
                      pop_pyramid_year(2017,fips),
                      ncol = 2,
                      nrow = 3,
                      legend= c("bottom"),
                      common.legend=TRUE) 
  # Add title to figure and save as image that is 8.5" x 11"
  annotate_figure(figure,
                  top = text_grob("Population Age and Sex Pyramids",size = 14))%>%
    ggexport(filename = paste0("PopPyramid_US_1970-2017_2020-01-15_",fips,".png"),
             width = 612, height = 792, pointsize = 8)
  
  return(figure)
}

# *******-*********-*********-*********-*********-*********-*********/
#  Explore Age and Sex Data                                         */
# *******-*********-*********-*********-*********-*********-*********/

# What is the fips code for the region you want to see the population pyramid for?
# Examples United States = 0, Alambama = 01000, Texas = 48000, Brazos County, TX = 48041

# Look at Population Pyarmid for one year
pop_pyramid_year(1970,48041)

# Generate figure with 6 population pyramids
pop_pyramid_6years(48041)

pop_pyramid_6years(04027)

# *******-*********-*********-*********-*********-*********-*********/
#  To go beyond this program refer to these websites                */
# *******-*********-*********-*********-*********-*********-*********/

# ggplot cheatsheet
# https://rstudio.com/wp-content/uploads/2015/03/ggplot2-cheatsheet.pdf

# Advanced population pyramids
# http://walkerke.github.io/2014/06/rcharts-pyramids/

# Fill color options
# http://www.sthda.com/english/wiki/ggplot2-colors-how-to-change-colors-automatically-and-manually
# http://www.sthda.com/english/wiki/colors-in-r
