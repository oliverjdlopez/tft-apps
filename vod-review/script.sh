#!/bin/bash

for i in {1..7}; do 
for j in {1..7}; do
for d in {"train","test"}; do
mkdir "$d/$i$j"
done
done
done    
 
